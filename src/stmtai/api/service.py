"""Everything the API does that is not HTTP: storage, applying corrections, building the reviewer's view.

Design decision: the **raw extraction is stored once and never modified**. Every view is rebuilt as
``raw -> apply human corrections -> score -> pin human-touched cells``. Three things follow:

* a correction re-runs the balance check, so fixing one wrong balance clears the flags it caused on its
  neighbours instead of leaving a stale review queue;
* corrections are an append-only log (with the confidence and flags the field had when the reviewer saw it),
  which is exactly the data needed to measure how good the confidence scores are;
* undo is deleting a log row.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

from ..extract.models import ExtractedStatement, ExtractedTransaction, FieldValue
from ..extract.parse import parse_date
from ..extract.scoring import review_items, score, threshold_for
from ..schema import money
from .reasons import reasons_for

DATE_FIELDS = {"date", "value_date", "period_start", "period_end"}
MONEY_FIELDS = {"debit", "credit", "balance", "opening_balance", "closing_balance"}
ROW_FIELDS = ["date", "value_date", "description", "ref", "debit", "credit", "balance"]
ACTIONS = {"correct", "confirm", "accept_suggestion"}


# --------------------------------------------------------------------------- values
def coerce_value(field: str, text: Optional[str]) -> Any:
    """Turn what a reviewer typed into the type the pipeline uses. Raises ValueError with a readable message."""
    text = (text or "").strip()
    if field in DATE_FIELDS:
        try:
            return dt.date.fromisoformat(text)
        except ValueError:
            d = parse_date(text)
            if d is None:
                raise ValueError(f"'{text}' is not a date. Use YYYY-MM-DD or DD/MM/YYYY.")
            return d
    if field in MONEY_FIELDS:
        if text == "":
            if field in ("debit", "credit", "value_date"):
                return None
            raise ValueError(f"{field} cannot be empty.")
        cleaned = text.replace(",", "").replace("₹", "").replace("Rs.", "").replace("INR", "").strip()
        try:
            return money(cleaned)
        except (InvalidOperation, ValueError):
            raise ValueError(f"'{text}' is not an amount.")
    return text


def _revive(field: str, value: Any) -> Any:
    """JSON turns dates and Decimals into strings; put the real types back (``FieldValue.value`` is untyped)."""
    if isinstance(value, str):
        if field in DATE_FIELDS:
            return dt.date.fromisoformat(value)
        if field in MONEY_FIELDS:
            return Decimal(value)
    return value


def rehydrate(ext: ExtractedStatement) -> ExtractedStatement:
    for name, fv in ext.header.items():
        fv.value, fv.suggestion = _revive(name, fv.value), _revive(name, fv.suggestion)
    for t in ext.transactions:
        for name, fv in t.fields.items():
            fv.value, fv.suggestion = _revive(name, fv.value), _revive(name, fv.suggestion)
    return ext


def to_json(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _field_json(fv: Optional[FieldValue], threshold: float, pages: int) -> Optional[dict]:
    if fv is None:
        return None
    return {
        "text": fv.text,
        "value": to_json(fv.value),
        "confidence": round(fv.confidence, 4),
        "needs_review": fv.confidence < threshold,
        "flags": fv.flags,
        "reasons": reasons_for(fv.flags, fv.confidence, fv.source) if fv.confidence < threshold else [],
        "suggestion": to_json(fv.suggestion),
        "suggestion_verified": "suggestion_verified" in fv.flags,
        "bbox": fv.bbox.model_dump() if fv.bbox else None,
        "source": fv.source,
    }


# --------------------------------------------------------------------------- corrections -> view
def apply_corrections(raw: ExtractedStatement, corrections: list[dict]) -> tuple[ExtractedStatement, dict[tuple, str]]:
    """Return (re-scored statement, {(row|None, field): 'human_corrected'|'human_verified'})."""
    ext = raw.model_copy(deep=True)
    human: dict[tuple, str] = {}
    for c in corrections:  # chronological; the latest action on a cell wins
        row, field, action = c["row"], c["field"], c["action"]
        if row is None:
            target = ext.header.get(field)
            if target is None:
                target = ext.header[field] = FieldValue(text="", confidence=0.0, source="human")
        else:
            if not 0 <= row < len(ext.transactions):
                continue
            fields = ext.transactions[row].fields
            target = fields.get(field)
            if target is None:
                target = fields[field] = FieldValue(text="", confidence=0.0, source="human")
        if action == "confirm":
            human[(row, field)] = "human_verified"
            continue
        target.value = coerce_value(field, c["new_value"]) if c["new_value"] is not None else None
        target.suggestion = None
        human[(row, field)] = "human_corrected"
    score(ext)
    for (row, field), kind in human.items():
        fv = ext.header.get(field) if row is None else ext.transactions[row].fields.get(field)
        if fv is None:
            continue
        fv.confidence, fv.suggestion, fv.flags = 1.0, None, [kind]
    flagged = review_items(ext)
    summary = ext.meta.setdefault("summary", {})
    summary["fields_to_review"] = len(flagged)
    summary["rows_to_review"] = len({r for r, _, _, _ in flagged if r is not None})
    return ext, human


def build_view(raw: ExtractedStatement, corrections: list[dict]) -> ExtractedStatement:
    return apply_corrections(raw, corrections)[0]


def statement_json(ext: ExtractedStatement) -> dict:
    return {
        "header": {k: _field_json(v, threshold_for(k), ext.pages) for k, v in ext.header.items()},
        "transactions": [
            {"row": i, "fields": {k: _field_json(v, threshold_for(k), ext.pages) for k, v in t.fields.items()}}
            for i, t in enumerate(ext.transactions)
        ],
        "issues": [{**i, **({"text": to_json(i["text"])} if "text" in i else {})} for i in ext.issues],
        "summary": ext.meta.get("summary", {}),
        "meta": {k: v for k, v in ext.meta.items() if k != "summary"},
    }


# id, label, hint, safe to confirm in one click. Order is the order a reviewer should work in:
# fixing a balance can clear other flags, so those come first.
GROUPS: list[dict] = [
    {"id": "chain", "label": "Balance does not add up", "hint": "Fix these first. They may clear other flags.", "bulk": False},
    {"id": "repaired", "label": "Date or amount repaired", "hint": "Scan damage fixed automatically.", "bulk": False},
    {"id": "text", "label": "Suggested text corrections", "hint": "From a rule or a language model, not checked by arithmetic. Compare each with the scan.", "bulk": False},
    {"id": "prefix", "label": "Payment prefix restored, digits match", "hint": "UPI/ or IMPS/ rebuilt; the reference column agrees.", "bulk": True},
    {"id": "header", "label": "Account details", "hint": "Name, number, IFSC, period.", "bulk": False},
    {"id": "other", "label": "Other low-confidence text", "hint": "The scan was hard to read here.", "bulk": False},
]


def group_of(row: Optional[int], field: str, flags: list[str]) -> str:
    if "balance_chain_break" in flags or "closing_mismatch" in flags:
        return "chain"
    if row is None:
        return "header"
    if "llm_suggested" in flags or "rule_suggested" in flags:
        return "text"
    if "prefix_snapped" in flags and "reference_matches" in flags:
        return "prefix"
    if "ocr_repaired" in flags and field in ("date", "value_date", "debit", "credit", "balance"):
        return "repaired"
    return "other"


def groups_summary(items: list[dict]) -> list[dict]:
    return [{**g, "count": sum(1 for i in items if i["group"] == g["id"])} for g in GROUPS]


def review_queue(ext: ExtractedStatement, order: str = "document") -> list[dict]:
    items = []
    for row, field, conf, flags in review_items(ext):
        fv = ext.header[field] if row is None else ext.transactions[row].fields[field]
        items.append({
            "key": f"h:{field}" if row is None else f"r{row}:{field}",
            "scope": "header" if row is None else "row", "row": row, "field": field,
            "text": fv.text, "value": to_json(fv.value), "confidence": round(conf, 4), "flags": flags,
            "reasons": reasons_for(flags, conf, fv.source), "suggestion": to_json(fv.suggestion),
            "suggestion_verified": "suggestion_verified" in flags,
            "bbox": fv.bbox.model_dump() if fv.bbox else None,
            "group": group_of(row, field, flags),
        })
    if order == "confidence":
        items.sort(key=lambda x: x["confidence"])
    else:
        items.sort(key=lambda x: (x["bbox"]["page"] if x["bbox"] else 0, -1 if x["row"] is None else x["row"], x["field"]))
    return items


def export_rows(ext: ExtractedStatement) -> list[dict]:
    out = []
    for i, t in enumerate(ext.transactions):
        row: dict[str, Any] = {f: to_json(t.value(f)) for f in ROW_FIELDS}
        row["needs_review"] = any(fv.confidence < threshold_for(k) for k, fv in t.fields.items())
        out.append(row)
    return out


def export_csv(ext: ExtractedStatement) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=ROW_FIELDS + ["needs_review"])
    w.writeheader()
    for r in export_rows(ext):
        w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    return buf.getvalue()


# --------------------------------------------------------------------------- storage
SCHEMA = """
CREATE TABLE IF NOT EXISTS statements (
  id TEXT PRIMARY KEY, filename TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
  created TEXT NOT NULL, approved_at TEXT, raw_json TEXT);
CREATE TABLE IF NOT EXISTS corrections (
  id INTEGER PRIMARY KEY AUTOINCREMENT, statement_id TEXT NOT NULL REFERENCES statements(id) ON DELETE CASCADE,
  row INTEGER, field TEXT NOT NULL, action TEXT NOT NULL,
  original_value TEXT, original_confidence REAL, original_flags TEXT, was_flagged INTEGER NOT NULL,
  had_suggestion INTEGER NOT NULL, new_value TEXT, created TEXT NOT NULL);
"""


class Store:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.uploads = self.dir / "uploads"
        self.pages = self.dir / "pages"
        for d in (self.uploads, self.pages):
            d.mkdir(parents=True, exist_ok=True)
        self.db_path = self.dir / "stmtai.db"
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        try:
            with self._lock:
                yield c
                c.commit()
        finally:
            c.close()

    @staticmethod
    def now() -> str:
        return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    def pdf_path(self, sid: str) -> Path:
        return self.uploads / f"{sid}.pdf"

    def create(self, filename: str) -> str:
        sid = uuid.uuid4().hex[:12]
        with self._conn() as c:
            c.execute("INSERT INTO statements(id, filename, status, created) VALUES (?,?,?,?)",
                      (sid, filename, "processing", self.now()))
        return sid

    def set_ready(self, sid: str, raw: ExtractedStatement) -> None:
        with self._conn() as c:
            c.execute("UPDATE statements SET status='ready', error=NULL, raw_json=? WHERE id=?",
                      (raw.model_dump_json(), sid))

    def set_failed(self, sid: str, error: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE statements SET status='failed', error=? WHERE id=?", (error, sid))

    def get(self, sid: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM statements WHERE id=?", (sid,)).fetchone()
        return dict(r) if r else None

    def list(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT id, filename, status, error, created, approved_at FROM statements "
                             "ORDER BY created DESC").fetchall()
        return [dict(r) for r in rows]

    def delete(self, sid: str) -> bool:
        with self._conn() as c:
            n = c.execute("DELETE FROM statements WHERE id=?", (sid,)).rowcount
        self.pdf_path(sid).unlink(missing_ok=True)
        for f in self.pages.glob(f"{sid}_*.png"):
            f.unlink(missing_ok=True)
        return bool(n)

    def raw(self, sid: str) -> Optional[ExtractedStatement]:
        rec = self.get(sid)
        if not rec or not rec["raw_json"]:
            return None
        return rehydrate(ExtractedStatement.model_validate_json(rec["raw_json"]))

    def approve(self, sid: str, approved: bool = True) -> None:
        with self._conn() as c:
            c.execute("UPDATE statements SET approved_at=? WHERE id=?", (self.now() if approved else None, sid))

    # corrections
    def add_correction(self, sid: str, row: Optional[int], field: str, action: str, original_value: Any,
                       original_confidence: float, original_flags: list[str], was_flagged: bool,
                       had_suggestion: bool, new_value: Optional[str]) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO corrections(statement_id,row,field,action,original_value,original_confidence,"
                "original_flags,was_flagged,had_suggestion,new_value,created) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (sid, row, field, action, None if original_value is None else str(to_json(original_value)),
                 original_confidence, json.dumps(original_flags), int(was_flagged), int(had_suggestion),
                 new_value, self.now()))
            return int(cur.lastrowid)

    def corrections(self, sid: Optional[str] = None) -> list[dict]:
        with self._conn() as c:
            q = "SELECT * FROM corrections" + (" WHERE statement_id=?" if sid else "") + " ORDER BY id"
            rows = c.execute(q, (sid,) if sid else ()).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["original_flags"] = json.loads(d["original_flags"] or "[]")
            d["was_flagged"], d["had_suggestion"] = bool(d["was_flagged"]), bool(d["had_suggestion"])
            out.append(d)
        return out

    def delete_correction(self, sid: str, cid: int) -> bool:
        with self._conn() as c:
            return bool(c.execute("DELETE FROM corrections WHERE id=? AND statement_id=?", (cid, sid)).rowcount)


def locate(ext: ExtractedStatement, row: Optional[int], field: str) -> Optional[FieldValue]:
    if row is None:
        return ext.header.get(field)
    if not 0 <= row < len(ext.transactions):
        return None
    return ext.transactions[row].fields.get(field)
