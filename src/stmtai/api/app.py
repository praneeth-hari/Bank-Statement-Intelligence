"""FastAPI application.

    python -m stmtai.api                         (or: uvicorn stmtai.api.app:create_app --factory)

Endpoints (all under the same origin; interactive docs at /docs):

    POST   /statements                          upload a PDF; extraction runs in the background
    GET    /statements                          list uploads
    GET    /statements/{id}                     full extraction with confidences, flags and boxes
    GET    /statements/{id}/review              only what needs a human, with reasons and suggestions
    GET    /statements/{id}/pages/{n}.png       page image to draw the boxes on
    POST   /statements/{id}/corrections         confirm / correct / accept a suggestion for one cell
    POST   /statements/{id}/corrections/bulk    confirm a whole low-risk group at once (e.g. restored UPI prefixes)
    DELETE /statements/{id}/corrections/{cid}   undo
    POST   /statements/{id}/approve             sign off (refused while cells still need review)
    GET    /statements/{id}/export.csv|json     corrected data
    POST   /query                               ask a question about approved statements; answered with the rows behind it
    GET    /feedback                            how well the confidence scores matched reviewer behaviour
    GET    /overview                            the dashboard's numbers, from approved statements only
    GET    /quality                             how far the confidence scores can be trusted, from the saved evaluation reports
    GET    /transactions                        filter, sort and page the transactions of approved statements
    GET    /categories, POST /categories, DELETE /categories/{id}   your own "contains this text, call it that" rules
    GET    /recurring                           payments that repeat across months
    GET    /transactions.csv                    every transaction on approved statements, as one CSV
    GET    /samples, POST /samples              the bundled synthetic statements; POST loads them (and approves the ones with nothing to review)
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from pathlib import Path
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from ..extract.pipeline import extract_pdf
from ..extract.scoring import review_items, threshold_for
from ..feedback import summarize
from ..llm.client import LLMUnavailable, from_spec
from ..llm.fallback import apply_rules, llm_fallback
from ..query.ask import ask as ask_question
from ..query.data import rows_from_extraction
from ..query.engine import run as run_query
from . import service
from .categories import STARTERS, UNCATEGORISED, category_of, first_rule
from .recurring import find_recurring
from .transactions import Filters
from .transactions import run as run_transactions
from .overview import Source, build_overview
from .quality import load_quality
from .service import ACTIONS, Store, apply_corrections, locate
from .transactions_export import transactions_csv

PDF_MAGIC = b"%PDF-"


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("STMTAI_DATA_DIR", "data/api")))
    ocr: bool = os.environ.get("STMTAI_OCR", "1") != "0"
    ocr_backend: Any = None  # inject an engine (tests, or a non-default one); None means RapidOCR
    ocr_cache_dir: Path = field(default_factory=lambda: Path(os.environ.get("STMTAI_OCR_CACHE", "data/ocr_cache")))
    # Optional LLM fallback: STMTAI_LLM=ollama or ollama:<model>. Inject a client in tests; None switches it off.
    llm: Any = field(default_factory=lambda: from_spec(os.environ.get("STMTAI_LLM")))
    api_key: Optional[str] = field(default_factory=lambda: os.environ.get("STMTAI_API_KEY") or None)
    max_upload_mb: int = int(os.environ.get("STMTAI_MAX_UPLOAD_MB", "25"))
    samples_dir: Path = field(default_factory=lambda: Path(os.environ.get("STMTAI_SAMPLES_DIR", "samples")))
    reports_dir: Path = field(default_factory=lambda: Path(os.environ.get("STMTAI_REPORTS_DIR", "reports")))
    cors_origins: list[str] = field(default_factory=lambda: [
        o for o in os.environ.get("STMTAI_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o])


class BulkIn(BaseModel):
    group: str  # only groups marked "bulk" in the review response can be confirmed in one go


class QueryIn(BaseModel):
    question: str
    statement_ids: Optional[list[str]] = None  # default: every approved statement
    parser: Literal["auto", "rules"] = "auto"  # "rules" never calls the model, even when one is configured


class RuleIn(BaseModel):
    pattern: str   # text to look for in a description, ignoring case
    category: str


class CorrectionIn(BaseModel):
    row: Optional[int] = None  # None for header fields
    field: str
    action: Literal["correct", "confirm", "accept_suggestion"]
    value: Optional[str] = None  # required for 'correct'; empty string clears a debit/credit/value date


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    cfg = settings or Settings()
    store = Store(cfg.data_dir)
    app = FastAPI(title="Bank Statement Intelligence", version="0.5.0",
                  description="Extract bank statements, score every field, review only what is doubtful.")
    app.add_middleware(CORSMiddleware, allow_origins=cfg.cors_origins, allow_methods=["*"], allow_headers=["*"])
    app.state.store, app.state.settings = store, cfg

    def auth(x_api_key: Optional[str] = Header(default=None)) -> None:
        if cfg.api_key and x_api_key != cfg.api_key:
            raise HTTPException(401, "Missing or wrong X-API-Key header.")

    def record_or_404(sid: str) -> dict:
        rec = store.get(sid)
        if rec is None:
            raise HTTPException(404, "No such statement.")
        return rec

    def ready_or_409(sid: str):
        rec = record_or_404(sid)
        if rec["status"] != "ready":
            raise HTTPException(409, f"Statement is {rec['status']}" + (f": {rec['error']}" if rec["error"] else "."))
        return rec, store.raw(sid)

    def process(sid: str) -> None:
        try:
            raw = extract_pdf(store.pdf_path(sid), ocr=cfg.ocr, ocr_backend=cfg.ocr_backend,
                              cache_dir=cfg.ocr_cache_dir, scored=False)
            known = store.approved_descriptions(exclude=sid)  # merchants a reviewer has already vouched for
            apply_rules(raw, known=known)  # deterministic text and date proposals; always on, cheap, and never overwrite
            if cfg.llm is not None:
                try:
                    cfg.llm.check()
                    llm_fallback(raw, cfg.llm, known=known)
                except LLMUnavailable as exc:  # extraction stands on its own; say why the model did not help
                    raw.meta["llm"] = {"status": "unavailable", "error": str(exc)}
            store.set_ready(sid, raw)
        except Exception as exc:  # reported on the record, never swallowed
            store.set_failed(sid, f"{type(exc).__name__}: {exc}")

    def summary_row(rec: dict, detail: bool = False) -> dict:
        out = {k: rec[k] for k in ("id", "filename", "status", "error", "created", "approved_at") if k in rec}
        out["approved"] = bool(rec.get("approved_at"))
        if detail and rec.get("status") == "ready":
            view = service.build_view(store.raw(rec["id"]), store.corrections(rec["id"]))
            s = view.meta.get("summary", {})
            out.update(rows=s.get("rows"), to_review=s.get("fields_to_review"), reconciles=s.get("reconciles"))
        return out

    def sample_files() -> list[Path]:
        """The digital sample PDFs (scans are slow to read, so the one-click demo leaves them out)."""
        if not cfg.samples_dir.is_dir():
            return []
        return sorted(p for p in cfg.samples_dir.glob("*.pdf") if "__scan_" not in p.name)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "ocr_enabled": cfg.ocr, "auth": bool(cfg.api_key),
                "llm": cfg.llm.name if cfg.llm is not None else None, "samples": len(sample_files())}

    @app.post("/samples", dependencies=[Depends(auth)])
    def load_samples() -> dict:
        """Load the bundled synthetic statements. A statement with nothing left to review is approved so the
        Dashboard fills at once; one that still needs a look stays waiting. Files already loaded are skipped."""
        have = {r["filename"] for r in store.list()}
        out = []
        for path in sample_files():
            if path.name in have:
                out.append({"filename": path.name, "result": "already loaded"})
                continue
            sid = store.create(path.name)
            store.pdf_path(sid).write_bytes(path.read_bytes())
            process(sid)
            rec = store.get(sid)
            approved = False
            if rec and rec["status"] == "ready":
                view = service.build_view(store.raw(sid), store.corrections(sid))
                if not view.meta["summary"]["fields_to_review"]:
                    store.approve(sid)
                    approved = True
            out.append({"filename": path.name, "id": sid, "result": "approved" if approved else (rec or {}).get("status", "failed")})
        return {"statements": out, "loaded": sum(1 for o in out if o["result"] != "already loaded")}

    def approved_rows() -> list:
        """Rows of every approved statement, oldest upload last as the store lists them. Unapproved ones never appear."""
        rows: list = []
        for rec in store.list():
            if rec.get("approved_at") and rec["status"] == "ready":
                view = service.build_view(store.raw(rec["id"]), store.corrections(rec["id"]))
                rows += rows_from_extraction(view, rec["id"], rec["filename"])
        return rows

    @app.get("/transactions", dependencies=[Depends(auth)])
    def transactions(q: Optional[str] = Query(None, max_length=100), date_from: Optional[dt.date] = None,
                     date_to: Optional[dt.date] = None, min_amount: Optional[Decimal] = Query(None, ge=0),
                     max_amount: Optional[Decimal] = Query(None, ge=0), type_: Optional[str] = Query(None, alias="type"),
                     direction: Literal["any", "debit", "credit"] = "any", statement_id: Optional[str] = None,
                     category: Optional[str] = None, sort: Literal["date", "amount"] = "date",
                     order: Literal["asc", "desc"] = "desc", limit: int = Query(100, ge=1, le=500),
                     offset: int = Query(0, ge=0)) -> dict:
        """Search approved statements. Every row links back to its statement; totals of the matches are exact and not netted."""
        f = Filters(q=(q or "").strip() or None, date_from=date_from, date_to=date_to, min_amount=min_amount,
                    max_amount=max_amount, type=type_, direction=direction, statement_id=statement_id,
                    category=category, sort=sort, order=order)
        return run_transactions(approved_rows(), store.rules(), f, limit, offset)

    @app.get("/categories", dependencies=[Depends(auth)])
    def categories() -> dict:
        rules, rows = store.rules(), approved_rows()
        have = {r.pattern.casefold() for r in rules}
        suggestions = []
        for pattern, cat in STARTERS:
            n = sum(1 for r in rows if pattern.casefold() in r.description.casefold() and first_rule(r.description, rules) is None)   # only what it would newly categorise
            if n and pattern.casefold() not in have:
                suggestions.append({"pattern": pattern, "category": cat, "matches": n})
        wins = [first_rule(r.description, rules) for r in rows]
        sorted_rules = [{"id": r.id, "pattern": r.pattern, "category": r.category,
                         "matches": sum(1 for w in wins if w is not None and w.id == r.id)} for r in rules]
        return {"rules": sorted_rules, "suggestions": suggestions,
                "coverage": {"total": len(rows), "categorised": sum(1 for r in rows if category_of(r.description, rules) != UNCATEGORISED)}}

    @app.post("/categories", status_code=201, dependencies=[Depends(auth)])
    def add_category(body: RuleIn) -> dict:
        try:
            rule = store.add_rule(body.pattern, body.category)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except KeyError:
            raise HTTPException(409, "There is already a rule for that text. Remove it first to change its category.")
        return {"id": rule.id, "pattern": rule.pattern, "category": rule.category}

    @app.delete("/categories/{rid}", status_code=204, dependencies=[Depends(auth)], response_model=None)
    def delete_category(rid: int) -> Response:
        if not store.delete_rule(rid):
            raise HTTPException(404, "No such rule.")
        return Response(status_code=204)

    @app.get("/recurring", dependencies=[Depends(auth)])
    def recurring() -> dict:
        return find_recurring(approved_rows())

    @app.get("/transactions.csv", dependencies=[Depends(auth)], response_model=None)
    def transactions_export() -> Response:
        """Every transaction on approved statements. Approved only, like the Dashboard it is downloaded from."""
        rows = approved_rows()
        if not rows:
            raise HTTPException(409, "No approved statements to export. Review and approve a statement first.")
        return Response(transactions_csv(rows), media_type="text/csv", headers={
            "Content-Disposition": 'attachment; filename="approved-transactions.csv"'})

    @app.post("/statements", status_code=202, dependencies=[Depends(auth)])
    def upload(background: BackgroundTasks, file: UploadFile = File(...)) -> dict:
        limit = cfg.max_upload_mb * 1024 * 1024
        head = file.file.read(len(PDF_MAGIC))
        if head != PDF_MAGIC:
            raise HTTPException(415, "Only PDF files are accepted.")
        sid = store.create(os.path.basename(file.filename or "statement.pdf"))
        size = len(head)
        try:
            with open(store.pdf_path(sid), "wb") as out:
                out.write(head)
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"File is larger than {cfg.max_upload_mb} MB.")
                    out.write(chunk)
        except HTTPException:
            store.delete(sid)
            raise
        background.add_task(process, sid)
        return {"id": sid, "status": "processing", "links": {"self": f"/statements/{sid}"}}

    @app.get("/statements", dependencies=[Depends(auth)])
    def list_statements() -> list[dict]:
        return [summary_row(r, detail=True) for r in store.list()]

    @app.get("/statements/{sid}", dependencies=[Depends(auth)])
    def get_statement(sid: str) -> dict:
        rec = record_or_404(sid)
        out = summary_row(rec)
        if rec["status"] != "ready":
            return out
        view = service.build_view(store.raw(sid), store.corrections(sid))
        import fitz

        with fitz.open(store.pdf_path(sid)) as doc:
            pages = [{"page": i, "width": p.rect.width, "height": p.rect.height,
                      "image": f"/statements/{sid}/pages/{i}.png"} for i, p in enumerate(doc)]
        return {**out, "pages": pages, **service.statement_json(view),
                "corrections": len(store.corrections(sid))}

    @app.get("/statements/{sid}/review", dependencies=[Depends(auth)])
    def review(sid: str, order: Literal["document", "confidence"] = "document") -> dict:
        _, raw = ready_or_409(sid)
        view = service.build_view(raw, store.corrections(sid))
        items = service.review_queue(view, order)
        return {"count": len(items), "items": items, "groups": service.groups_summary(items),
                "reconciles": view.meta["summary"]["reconciles"]}

    @app.get("/statements/{sid}/pages/{page}.png", dependencies=[Depends(auth)], response_model=None)
    def page_image(sid: str, page: int, dpi: int = Query(110, ge=50, le=220)) -> FileResponse:
        record_or_404(sid)
        cached = store.pages / f"{sid}_{page}_{dpi}.png"
        if not cached.exists():
            import fitz

            with fitz.open(store.pdf_path(sid)) as doc:
                if not 0 <= page < len(doc):
                    raise HTTPException(404, "No such page.")
                doc[page].get_pixmap(dpi=dpi).save(cached)
        return FileResponse(cached, media_type="image/png")

    @app.post("/statements/{sid}/corrections", status_code=201, dependencies=[Depends(auth)])
    def correct(sid: str, body: CorrectionIn) -> dict:
        rec, raw = ready_or_409(sid)
        if rec["approved_at"]:
            raise HTTPException(409, "Statement is approved. Reopen it to change it.")
        previous = store.corrections(sid)
        view, _ = apply_corrections(raw, previous)  # what the reviewer is looking at right now
        fv = locate(view, body.row, body.field)
        if fv is None and body.action != "correct":
            raise HTTPException(404, "No such field.")
        if body.action == "accept_suggestion":
            if fv.suggestion is None and "suggest_clear" not in fv.flags:
                raise HTTPException(422, "This field has no suggestion to accept.")
            new_value = None if fv.suggestion is None else str(service.to_json(fv.suggestion))
        elif body.action == "correct":
            if body.value is None:
                raise HTTPException(422, "'correct' needs a value.")
            new_value = body.value
        else:
            new_value = None
        if new_value is not None:
            try:
                service.coerce_value(body.field, new_value)
            except ValueError as exc:
                raise HTTPException(422, str(exc))
        elif body.action == "accept_suggestion":
            new_value = ""  # clear the cell
        threshold = threshold_for(body.field)
        cid = store.add_correction(
            sid, body.row, body.field, body.action,
            fv.value if fv else None, fv.confidence if fv else 0.0, fv.flags if fv else [],
            was_flagged=bool(fv and fv.confidence < threshold), had_suggestion=bool(fv and fv.suggestion is not None),
            new_value=new_value)
        after = service.build_view(raw, store.corrections(sid))
        return {"id": cid, "remaining_to_review": after.meta["summary"]["fields_to_review"],
                "reconciles": after.meta["summary"]["reconciles"]}

    @app.post("/statements/{sid}/corrections/bulk", status_code=201, dependencies=[Depends(auth)])
    def confirm_group(sid: str, body: BulkIn) -> dict:
        """Confirm every cell in a low-risk group at once. Each cell still gets its own log row, so the
        feedback metrics see 24 confirmations, not one."""
        rec, raw = ready_or_409(sid)
        if rec["approved_at"]:
            raise HTTPException(409, "Statement is approved. Reopen it to change it.")
        group = next((g for g in service.GROUPS if g["id"] == body.group), None)
        if group is None:
            raise HTTPException(404, "No such group.")
        if not group["bulk"]:
            raise HTTPException(422, f"'{group['label']}' needs a look at each item and cannot be confirmed in bulk.")
        view, _ = apply_corrections(raw, store.corrections(sid))
        items = [i for i in service.review_queue(view) if i["group"] == body.group]
        ids = []
        for i in items:
            fv = locate(view, i["row"], i["field"])
            ids.append(store.add_correction(sid, i["row"], i["field"], "confirm", fv.value, fv.confidence, fv.flags,
                                            was_flagged=True, had_suggestion=fv.suggestion is not None, new_value=None))
        after = service.build_view(raw, store.corrections(sid))
        return {"confirmed": len(items), "ids": ids, "remaining_to_review": after.meta["summary"]["fields_to_review"],
                "reconciles": after.meta["summary"]["reconciles"]}

    @app.get("/statements/{sid}/corrections", dependencies=[Depends(auth)])
    def list_corrections(sid: str) -> list[dict]:
        record_or_404(sid)
        return store.corrections(sid)

    @app.delete("/statements/{sid}/corrections/{cid}", dependencies=[Depends(auth)])
    def undo(sid: str, cid: int) -> dict:
        rec = record_or_404(sid)
        if rec["approved_at"]:
            raise HTTPException(409, "Statement is approved. Reopen it to change it.")
        if not store.delete_correction(sid, cid):
            raise HTTPException(404, "No such correction.")
        return {"deleted": cid}

    @app.post("/statements/{sid}/approve", dependencies=[Depends(auth)], response_model=None)
    def approve(sid: str, force: bool = False) -> JSONResponse | dict:
        _, raw = ready_or_409(sid)
        view = service.build_view(raw, store.corrections(sid))
        left = view.meta["summary"]["fields_to_review"]
        if left and not force:
            return JSONResponse(status_code=409, content={
                "detail": f"{left} field(s) still need review. Review them, or approve with force=true.",
                "remaining_to_review": left})
        store.approve(sid)
        return {"approved": True, "remaining_to_review": left, "reconciles": view.meta["summary"]["reconciles"]}

    @app.post("/statements/{sid}/reopen", dependencies=[Depends(auth)])
    def reopen(sid: str) -> dict:
        record_or_404(sid)
        store.approve(sid, approved=False)
        return {"approved": False}

    @app.get("/statements/{sid}/export.{fmt}", dependencies=[Depends(auth)], response_model=None)
    def export(sid: str, fmt: Literal["csv", "json"]) -> Response:
        rec, raw = ready_or_409(sid)
        view = service.build_view(raw, store.corrections(sid))
        left = view.meta["summary"]["fields_to_review"]
        headers = {"X-Fields-Needing-Review": str(left), "X-Approved": str(bool(rec["approved_at"])).lower()}
        if fmt == "csv":
            return Response(service.export_csv(view), media_type="text/csv", headers={
                **headers, "Content-Disposition": f'attachment; filename="{sid}.csv"'})
        body = {"id": sid, "approved": bool(rec["approved_at"]), "fields_needing_review": left,
                "header": {k: service.to_json(v.value) for k, v in view.header.items()},
                "transactions": service.export_rows(view)}
        return JSONResponse(body, headers=headers)

    @app.delete("/statements/{sid}", status_code=204, dependencies=[Depends(auth)], response_model=None)
    def delete(sid: str) -> Response:
        if not store.delete(sid):
            raise HTTPException(404, "No such statement.")
        return Response(status_code=204)

    @app.post("/query", dependencies=[Depends(auth)])
    def query(body: QueryIn) -> dict:
        """Answer a question from approved statements only, so a number is never built on cells nobody has checked."""
        approved = [r for r in store.list() if r.get("approved_at") and r["status"] == "ready"]
        if body.statement_ids is not None:
            wanted = set(body.statement_ids)
            unknown = wanted - {r["id"] for r in store.list()}
            if unknown:
                raise HTTPException(404, f"No such statement: {sorted(unknown)[0]}")
            not_approved = wanted - {r["id"] for r in approved}
            if not_approved:
                raise HTTPException(409, f"Statement {sorted(not_approved)[0]} is not approved yet, so it cannot be queried.")
            approved = [r for r in approved if r["id"] in wanted]
        if not approved:
            raise HTTPException(409, "No approved statements to ask about. Review and approve a statement first.")
        rows, total, skipped = [], 0, 0
        for rec in approved:
            view = service.build_view(store.raw(rec["id"]), store.corrections(rec["id"]))
            got = rows_from_extraction(view, rec["id"], rec["filename"])
            rows += got
            total += len(view.transactions)
            skipped += len(view.transactions) - len(got)
        client = cfg.llm if body.parser == "auto" else None
        res = ask_question(body.question, rows, client=client)
        out: dict[str, Any] = {"question": body.question, "answered": res.answered, "statements": [r["id"] for r in approved],
                               "rows_considered": len(rows), "rows_skipped": skipped, "parser": res.parser, "notes": list(res.notes)}
        if len(approved) > 1:
            out["notes"].append(f"Combined {len(approved)} statements; they may belong to different accounts.")
        if skipped:
            out["notes"].append(f"{skipped} of {total} rows were left out because they lack a date, a balance or a single amount.")
        if not res.answered:
            out["reason"] = res.reason
            return out
        a = res.answer
        if res.query.aggregate == "last" and len(approved) > 1:
            # A balance belongs to one account: answer once per statement instead of picking one and calling it "the" balance.
            per = []
            for rec in approved:
                mine = [r for r in rows if r.statement_id == rec["id"]]
                one = run_query(res.query, mine)
                if one.kind == "number":
                    per.append((rec["filename"], one.value, one.rows[0]))
            if per:
                out["notes"] = [n for n in out["notes"] if "different accounts" not in n]
                out["notes"].append("Each statement is shown separately, because a balance belongs to one account.")
                out.update(interpretation=res.interpretation + ", per statement", query=res.query.model_dump(mode="json"),
                           kind="groups", unit=a.unit, matched=a.matched, value=None,
                           groups=[{"key": name, "value": service.to_json(v)} for name, v, _ in per],
                           rows=[{"statement_id": r.statement_id, "filename": r.filename, "row": r.row, "date": r.date.isoformat(),
                                  "description": r.description, "debit": service.to_json(r.debit), "credit": service.to_json(r.credit),
                                  "balance": service.to_json(r.balance)} for _, _, r in per])
                return out
        out.update(interpretation=res.interpretation, query=res.query.model_dump(mode="json"), kind=a.kind, unit=a.unit,
                   matched=a.matched, value=service.to_json(a.value),
                   groups=[{"key": k, "value": service.to_json(v)} for k, v in a.groups],
                   rows=[{"statement_id": r.statement_id, "filename": r.filename, "row": r.row, "date": r.date.isoformat(),
                          "description": r.description, "debit": service.to_json(r.debit), "credit": service.to_json(r.credit),
                          "balance": service.to_json(r.balance)} for r in a.rows])
        return out

    @app.get("/feedback", dependencies=[Depends(auth)])
    def feedback() -> dict:
        return summarize(store.corrections())

    @app.get("/overview", dependencies=[Depends(auth)])
    def overview() -> dict:
        """The dashboard: totals, months, types, balances and largest debits from approved statements only."""
        recs = store.list()
        counts = {"total": len(recs), "approved": 0, "awaiting": 0, "processing": 0, "failed": 0, "fields_to_review": 0}
        sources = []
        for rec in recs:
            if rec["status"] == "processing":
                counts["processing"] += 1
                continue
            if rec["status"] != "ready":
                counts["failed"] += 1
                continue
            view = service.build_view(store.raw(rec["id"]), store.corrections(rec["id"]))
            if not rec.get("approved_at"):
                counts["awaiting"] += 1
                counts["fields_to_review"] += view.meta.get("summary", {}).get("fields_to_review") or 0
                continue
            counts["approved"] += 1

            def iso(v: Any) -> Optional[str]:
                return v.isoformat() if hasattr(v, "isoformat") else None

            sources.append(Source(rec["id"], rec["filename"], view.header_value("bank_name") or None,
                                  iso(view.header_value("period_start")), iso(view.header_value("period_end")),
                                  rows_from_extraction(view, rec["id"], rec["filename"])))
        return build_overview(sources, counts, store.rules())

    @app.get("/quality", dependencies=[Depends(auth)])
    def quality() -> dict:
        """Evaluation numbers from the saved reports, plus what reviewers on this installation actually did."""
        out = load_quality(cfg.reports_dir)
        out["reviewer"] = {k: v for k, v in summarize(store.corrections())["overall"].items()
                           if k in ("reviewed", "flagged_reviewed", "flagged_actually_wrong", "unflagged_corrected")}
        return out

    return app

