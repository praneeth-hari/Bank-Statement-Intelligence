"""Measure the LLM fallback against the synthetic ground truth.

    python -m stmtai.llm.evaluate --kind scan_medium --model qwen2.5:3b --limit 12

For every cell the model is asked about, the truth is known, so each answer can be scored:

* **fixed**   the value read was wrong and the suggestion is right  (the model helped)
* **broke**   the value read was right and the suggestion is wrong  (a reviewer could be misled)
* **missed**  the value read was wrong and the suggestion is wrong too (or there is none)

The report also shows what the validators did: how many of the model's raw answers they dropped, and how many of
those would have been wrong. A model is only worth wiring in if ``fixed`` clearly exceeds ``broke`` *after* the
checks, and the report is built so that is the first thing you see.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from ..evaluate import align, char_errors, values_equal
from ..extract.pipeline import extract_pdf
from ..schema import Label
from .client import LLMUnavailable, OllamaClient
from .fallback import FLAG, RULE_FLAG, candidates, suggest


def _new() -> dict[str, int]:
    return defaultdict(int)


def evaluate_doc(label: Label, ext, client: Optional[OllamaClient], trace_sink: list[dict], batch_size: int,
                 known: Optional[list[str]] = None) -> dict[str, Any]:
    """``client=None`` scores the rules alone."""
    truth = label.statement.transactions
    pairs = {j: i for i, j in align(truth, ext.transactions) if i is not None and j is not None}
    asked = candidates(ext)
    after = ext.model_copy(deep=True)
    trace: list[dict] = []
    suggest(after, client, batch_size=batch_size, max_cells=10_000, trace=trace, known=known or [])

    per: dict[str, dict[str, int]] = defaultdict(_new)
    chars = {"read": 0, "after": 0, "length": 0}
    for row, name in asked:
        i = pairs.get(row)
        if i is None:
            per[name]["unaligned"] += 1
            continue
        want = getattr(truth[i], name)
        fv = after.transactions[row].fields[name]
        read_ok = values_equal(name, want, fv.value)
        source = "rule" if RULE_FLAG in fv.flags else "llm" if FLAG in fv.flags else None
        sug = fv.suggestion if source else None
        sug_ok = sug is not None and values_equal(name, want, sug)
        c = per[name]
        c["asked"] += 1
        c["read_right"] += read_ok
        c["read_wrong"] += not read_ok
        if sug is not None:
            c["proposed"] += 1
            c["proposed_right"] += sug_ok
            c["fixed"] += (not read_ok) and sug_ok
            c["broke"] += read_ok and not sug_ok
            for key, hit in (("proposed", True), ("fixed", (not read_ok) and sug_ok), ("broke", read_ok and not sug_ok)):
                c[f"{source}_{key}"] += hit
        c["missed"] += (not read_ok) and not sug_ok
        if name == "description":
            e0, n = char_errors(name, want, fv.value)
            e1, _ = char_errors(name, want, sug if sug is not None else fv.value)
            chars["read"] += e0
            chars["after"] += e1
            chars["length"] += n
        # what the model said before the checks
        for t in trace:
            if t["row"] == row and t["field"] == name and t["answer"] is not None and t.get("source") == "llm":
                ok = _answer_right(name, want, t["answer"])
                per[name]["raw_answers"] += 1
                per[name]["raw_right"] += ok
                if t["rejected"]:
                    per[name]["blocked"] += 1
                    per[name]["blocked_right"] += ok
                    per[name]["blocked_would_have_broken"] += read_ok and not ok
    trace_sink.extend(trace)
    return {"doc": label.doc_id, "per_field": {k: dict(v) for k, v in per.items()}, "chars": chars,
            "llm": after.meta.get("llm", {})}


def _answer_right(name: str, want: Any, answer: str) -> bool:
    if name in ("date", "value_date"):
        return str(want) == answer.strip()
    return values_equal(name, want, answer)


def summarize(docs: list[dict]) -> dict[str, Any]:
    total: dict[str, dict[str, int]] = defaultdict(_new)
    chars = {"read": 0, "after": 0, "length": 0}
    for d in docs:
        for name, c in d["per_field"].items():
            for k, v in c.items():
                total[name][k] += v
        for k in chars:
            chars[k] += d["chars"][k]
    return {"fields": {k: dict(v) for k, v in total.items()}, "chars": chars, "docs": len(docs)}


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "n/a"


def render(summary: dict, model: str, kind: str, client: Optional[OllamaClient], extra: dict) -> str:
    out = [f"# Text and date suggestions on {kind} ({summary['docs']} documents), "
           + (f"rules plus model `{model}`" if client is not None else "rules only"), ""]
    f = summary["fields"]
    fixed = sum(c.get("fixed", 0) for c in f.values())
    broke = sum(c.get("broke", 0) for c in f.values())
    asked = sum(c.get("asked", 0) for c in f.values())
    out += [f"**Net effect: {fixed} cells fixed, {broke} correct cells put at risk, out of {asked} asked about.**", ""]
    out += ["| field | asked | read wrong | proposed | suggestion right | fixed | broke | still wrong |",
            "|---|---|---|---|---|---|---|---|"]
    for name, c in sorted(f.items()):
        out.append(f"| {name} | {c.get('asked', 0)} | {c.get('read_wrong', 0)} | {c.get('proposed', 0)} | "
                   f"{_pct(c.get('proposed_right', 0), c.get('proposed', 0))} | {c.get('fixed', 0)} | "
                   f"{c.get('broke', 0)} | {c.get('missed', 0)} |")
    ch = summary["chars"]
    if ch["length"]:
        out += ["", f"Description character errors on the cells asked: {ch['read']} before, {ch['after']} after "
                    f"({_pct(ch['read'], ch['length'])} to {_pct(ch['after'], ch['length'])} of characters)."]
    out += ["", "## Rules versus the model", "",
            "| field | rule proposals | rule fixed | rule broke | model proposals | model fixed | model broke |",
            "|---|---|---|---|---|---|---|"]
    for name, c in sorted(f.items()):
        out.append(f"| {name} | {c.get('rule_proposed', 0)} | {c.get('rule_fixed', 0)} | {c.get('rule_broke', 0)} | "
                   f"{c.get('llm_proposed', 0)} | {c.get('llm_fixed', 0)} | {c.get('llm_broke', 0)} |")
    out += ["", "## What the checks did to the model's answers", "",
            "| field | raw answers | raw answers right | blocked by checks | blocked that were right | blocked that would have broken a correct cell |",
            "|---|---|---|---|---|---|"]
    for name, c in sorted(f.items()):
        out.append(f"| {name} | {c.get('raw_answers', 0)} | {_pct(c.get('raw_right', 0), c.get('raw_answers', 0))} | "
                   f"{c.get('blocked', 0)} | {c.get('blocked_right', 0)} | {c.get('blocked_would_have_broken', 0)} |")
    if client is not None:
        secs = client.seconds
        out += ["", "## Cost", "",
                f"{client.calls} model calls, {secs:.0f}s total"
                + (f", {secs / client.calls:.1f}s per call" if client.calls else "")
                + f"; {client.cache_hits} answered from the cache. {extra.get('docs_failed', 0)} documents failed to extract."]
    else:
        out += ["", f"{extra.get('docs_failed', 0)} documents failed to extract."]
    return "\n".join(out)


def main() -> None:
    p = argparse.ArgumentParser(description="Score the Ollama fallback against synthetic ground truth.")
    p.add_argument("--data", type=Path, default=Path("data/synthetic"))
    p.add_argument("--kind", default="scan_medium", help="scan_light, scan_medium or scan_heavy")
    p.add_argument("--model", default=None, help="Ollama model tag (default: STMTAI_LLM_MODEL or qwen2.5:3b)")
    p.add_argument("--host", default=None)
    p.add_argument("--limit", type=int, default=0, help="only the first N documents (0 = all)")
    p.add_argument("--batch", type=int, default=6)
    p.add_argument("--engine", default="rapidocr", help="OCR engine for the extraction (rapidocr, cached:<engine>)")
    p.add_argument("--cache", type=Path, default=Path("data/llm_cache"), help="stores model replies; delete to re-ask")
    p.add_argument("--pool", action="store_true",
                   help="treat the other documents' true descriptions as approved statements the names can be learned from")
    p.add_argument("--no-model", action="store_true", help="score the rules alone; Ollama is not needed")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    kwargs: dict[str, Any] = {"cache_dir": args.cache}
    if args.model:
        kwargs["model"] = args.model
    if args.host:
        kwargs["host"] = args.host
    client: Optional[OllamaClient] = None
    if not args.no_model:
        client = OllamaClient(**kwargs)
        client.check()  # fail early with a clear message rather than after an hour of OCR

    from ..extract.ocr import get_backend

    backend = get_backend(args.engine)
    all_labels = {lp.stem: Label.model_validate_json(lp.read_text(encoding="utf-8")) for lp in sorted(args.data.glob("*.json"))}
    docs: list[dict] = []
    failed = 0
    trace: list[dict] = []
    for lp in sorted(args.data.glob("*.json")):
        label = Label.model_validate_json(lp.read_text(encoding="utf-8"))
        pdf = args.data / f"{label.doc_id}__{args.kind}.pdf"
        if not pdf.exists():
            continue
        if args.limit and len(docs) + failed >= args.limit:
            break
        try:
            ext = extract_pdf(pdf, ocr_backend=backend)
            known = [t.description for k, lb in all_labels.items() if k != lp.stem for t in lb.statement.transactions] if args.pool else []
            docs.append(evaluate_doc(label, ext, client, trace, args.batch, known))
            print(f"{label.doc_id}: done ({len(docs)} documents)", flush=True)
        except LLMUnavailable:
            raise
        except Exception as exc:  # a document that cannot be extracted is reported, not hidden
            failed += 1
            print(f"{label.doc_id}: extraction failed ({type(exc).__name__}: {exc})", flush=True)
    if not docs:
        raise SystemExit(f"no documents of kind '{args.kind}' evaluated in {args.data}")
    summary = summarize(docs)
    report = render(summary, client.model if client else "", args.kind, client, {"docs_failed": failed})
    print("\n" + report)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "report.md").write_text(report, encoding="utf-8")
        (args.out / "metrics.json").write_text(json.dumps({"model": client.model if client else None, "kind": args.kind, **summary,
                                                            "documents": docs}, indent=2, default=str), encoding="utf-8")
        (args.out / "answers.jsonl").write_text("\n".join(json.dumps(t, default=str) for t in trace), encoding="utf-8")
        print(f"Wrote report.md, metrics.json and answers.jsonl to {args.out}")


if __name__ == "__main__":
    main()
