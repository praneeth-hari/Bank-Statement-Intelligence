"""Evaluate extraction against synthetic ground truth.

    python -m stmtai.evaluate --data data/synthetic --kind digital --out data/runs/digital

Rows are aligned to ground truth with a small dynamic program (so one dropped or extra row does not
shift every later comparison), then every field is compared exactly after light normalisation
(whitespace and case for text, numeric equality for money).

The report also measures the review loop: how many fields get flagged for a human, and what share of
the wrong fields those flags catch.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .extract.models import ExtractedStatement, ExtractedTransaction
from .extract.pipeline import extract_pdf
from .extract.scoring import REVIEW_THRESHOLD
from .schema import Label, Transaction

HEADER_FIELDS = ["bank_name", "account_holder", "account_number", "ifsc", "branch",
                 "period_start", "period_end", "opening_balance", "closing_balance", "currency"]
ROW_FIELDS = ["date", "value_date", "description", "ref", "debit", "credit", "balance"]
ALIGN_FIELDS = ["date", "description", "debit", "credit", "balance"]
_TEXT_FIELDS = {"description", "ref", "bank_name", "account_holder", "branch"}
_CODE_FIELDS = {"account_number", "ifsc", "currency"}


# --------------------------------------------------------------------------- comparison
def _norm(name: str, value: Any) -> Any:
    if value is None:
        return None
    if name in _TEXT_FIELDS:
        return "".join(str(value).split()).casefold() or None
    if name in _CODE_FIELDS:
        return "".join(str(value).split()).upper() or None
    return value


def values_equal(name: str, truth: Any, got: Any) -> bool:
    return _norm(name, truth) == _norm(name, got)


def _pair_score(truth: Transaction, got: ExtractedTransaction) -> float:
    hits = sum(values_equal(f, getattr(truth, f), got.value(f)) for f in ALIGN_FIELDS)
    return hits / len(ALIGN_FIELDS)


def align(truth: list[Transaction], got: list[ExtractedTransaction],
          min_score: float = 0.4) -> list[tuple[Optional[int], Optional[int]]]:
    """Order-preserving alignment maximising total similarity. Returns (truth_idx, got_idx) pairs;
    one side is None for a missed or spurious row."""
    n, m = len(truth), len(got)
    sim = [[_pair_score(truth[i], got[j]) for j in range(m)] for i in range(n)]
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best = max(dp[i - 1][j], dp[i][j - 1])
            if sim[i - 1][j - 1] >= min_score:
                best = max(best, dp[i - 1][j - 1] + sim[i - 1][j - 1])
            dp[i][j] = best

    pairs: list[tuple[Optional[int], Optional[int]]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and sim[i - 1][j - 1] >= min_score and dp[i][j] == dp[i - 1][j - 1] + sim[i - 1][j - 1]:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j]:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    return pairs[::-1]


# --------------------------------------------------------------------------- per document
@dataclass
class DocEval:
    doc_id: str
    layout: str
    kind: str
    truth_rows: int = 0
    got_rows: int = 0
    matched_rows: int = 0
    row_total: dict[str, int] = field(default_factory=dict)
    row_correct: dict[str, int] = field(default_factory=dict)
    header_total: dict[str, int] = field(default_factory=dict)
    header_correct: dict[str, int] = field(default_factory=dict)
    conf_pairs: list[tuple[float, bool]] = field(default_factory=list)  # (confidence, was_correct)
    reconciles: bool = False
    exact: bool = False
    error: str = ""
    examples: list[dict] = field(default_factory=list)


def _bump(d: dict[str, int], key: str, by: int = 1) -> None:
    d[key] = d.get(key, 0) + by


def evaluate_pair(label: Label, ext: ExtractedStatement, kind: str = "digital", max_examples: int = 15) -> DocEval:
    ev = DocEval(label.doc_id, label.layout, kind)
    truth = label.statement.transactions
    got = ext.transactions
    ev.truth_rows, ev.got_rows = len(truth), len(got)
    fields = [f for f in ROW_FIELDS if f in label.fields_present]
    all_correct = True

    for ti, gi in align(truth, got):
        if ti is None:
            continue
        if gi is not None:
            ev.matched_rows += 1
        for f in fields:
            _bump(ev.row_total, f)
            expected = getattr(truth[ti], f)
            if gi is None:
                all_correct = False
                continue
            actual = got[gi].value(f)
            ok = values_equal(f, expected, actual)
            if ok:
                _bump(ev.row_correct, f)
            else:
                all_correct = False
                if len(ev.examples) < max_examples:
                    ev.examples.append({"doc": label.doc_id, "row": ti, "field": f,
                                        "truth": str(expected), "got": str(actual)})
            fv = got[gi].fields.get(f)
            if fv is not None:
                ev.conf_pairs.append((fv.confidence, ok))

    for f in HEADER_FIELDS:
        _bump(ev.header_total, f)
        expected = getattr(label.statement, f)
        fv = ext.header.get(f)
        actual = fv.value if fv else None
        ok = values_equal(f, expected, actual)
        if ok:
            _bump(ev.header_correct, f)
        else:
            all_correct = False
            if len(ev.examples) < max_examples:
                ev.examples.append({"doc": label.doc_id, "row": None, "field": f,
                                    "truth": str(expected), "got": str(actual)})
        if fv is not None:
            ev.conf_pairs.append((fv.confidence, ok))

    ev.reconciles = bool(ext.meta.get("summary", {}).get("reconciles", False))
    ev.exact = all_correct and ev.truth_rows == ev.got_rows
    return ev


# --------------------------------------------------------------------------- aggregation
def _ratio(a: float, b: float) -> Optional[float]:
    return round(a / b, 4) if b else None


def summarize(docs: list[DocEval]) -> dict:
    def block(items: list[DocEval]) -> dict:
        row_total: dict[str, int] = {}
        row_correct: dict[str, int] = {}
        head_total: dict[str, int] = {}
        head_correct: dict[str, int] = {}
        pairs: list[tuple[float, bool]] = []
        for d in items:
            for k, v in d.row_total.items():
                _bump(row_total, k, v)
            for k, v in d.row_correct.items():
                _bump(row_correct, k, v)
            for k, v in d.header_total.items():
                _bump(head_total, k, v)
            for k, v in d.header_correct.items():
                _bump(head_correct, k, v)
            pairs += d.conf_pairs
        truth_rows = sum(d.truth_rows for d in items)
        got_rows = sum(d.got_rows for d in items)
        matched = sum(d.matched_rows for d in items)
        flagged = [(c, ok) for c, ok in pairs if c < REVIEW_THRESHOLD]
        wrong = [(c, ok) for c, ok in pairs if not ok]
        caught = [p for p in wrong if p[0] < REVIEW_THRESHOLD]
        return {
            "docs": len(items),
            "failed_docs": sum(1 for d in items if d.error),
            "rows_truth": truth_rows,
            "rows_extracted": got_rows,
            "row_recall": _ratio(matched, truth_rows),
            "row_precision": _ratio(matched, got_rows),
            "row_field_accuracy": _ratio(sum(row_correct.values()), sum(row_total.values())),
            "header_field_accuracy": _ratio(sum(head_correct.values()), sum(head_total.values())),
            "exact_match_docs": _ratio(sum(d.exact for d in items), len(items)),
            "reconcile_rate": _ratio(sum(d.reconciles for d in items), len(items)),
            "per_field_accuracy": {k: _ratio(row_correct.get(k, 0), v) for k, v in sorted(row_total.items())},
            "per_header_accuracy": {k: _ratio(head_correct.get(k, 0), v) for k, v in sorted(head_total.items())},
            "review": {
                "threshold": REVIEW_THRESHOLD,
                "fields_compared": len(pairs),
                "fields_flagged": len(flagged),
                "flag_rate": _ratio(len(flagged), len(pairs)),
                "wrong_fields": len(wrong),
                "wrong_caught_by_flags": len(caught),
                "error_recall": _ratio(len(caught), len(wrong)),
                "flag_precision": _ratio(sum(1 for _, ok in flagged if not ok), len(flagged)),
            },
        }

    layouts = sorted({d.layout for d in docs})
    return {
        "overall": block(docs),
        "by_layout": {name: block([d for d in docs if d.layout == name]) for name in layouts},
        "errors": [e for d in docs for e in d.examples][:50],
        "failures": [{"doc": d.doc_id, "error": d.error} for d in docs if d.error],
    }


def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def render_markdown(summary: dict, kind: str) -> str:
    o = summary["overall"]
    lines = [
        f"# Extraction report: `{kind}`", "",
        f"{o['docs']} documents, {o['rows_truth']} ground-truth rows. "
        f"Row recall {_pct(o['row_recall'])}, row precision {_pct(o['row_precision'])}, "
        f"row-field accuracy {_pct(o['row_field_accuracy'])}, header accuracy {_pct(o['header_field_accuracy'])}, "
        f"exact-match documents {_pct(o['exact_match_docs'])}.", "",
        "| Layout | Docs | Rows (truth / extracted) | Row recall | Row precision | Field accuracy | Header accuracy | Exact docs | Reconciles |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, b in summary["by_layout"].items():
        lines.append(f"| {name} | {b['docs']} | {b['rows_truth']} / {b['rows_extracted']} | {_pct(b['row_recall'])} | "
                     f"{_pct(b['row_precision'])} | {_pct(b['row_field_accuracy'])} | {_pct(b['header_field_accuracy'])} | "
                     f"{_pct(b['exact_match_docs'])} | {_pct(b['reconcile_rate'])} |")
    lines += ["", "## Accuracy by field (all layouts)", "", "| Field | Accuracy |", "|---|---|"]
    lines += [f"| {k} | {_pct(v)} |" for k, v in o["per_field_accuracy"].items()]
    lines += ["", "## Header fields", "", "| Field | Accuracy |", "|---|---|"]
    lines += [f"| {k} | {_pct(v)} |" for k, v in o["per_header_accuracy"].items()]
    r = o["review"]
    lines += [
        "", "## Human-review loop", "",
        f"Fields below the {r['threshold']:.2f} confidence threshold are sent to review: "
        f"{r['fields_flagged']} of {r['fields_compared']} compared fields ({_pct(r['flag_rate'])}). "
        f"Wrong fields: {r['wrong_fields']}; caught by a flag: {r['wrong_caught_by_flags']} "
        f"(error recall {_pct(r['error_recall'])}, flag precision {_pct(r['flag_precision'])}).",
    ]
    if summary["errors"]:
        lines += ["", "## Example errors", "", "| Doc | Row | Field | Truth | Got |", "|---|---|---|---|---|"]
        lines += [f"| {e['doc']} | {e['row']} | {e['field']} | {e['truth']} | {e['got']} |" for e in summary["errors"][:15]]
    if summary["failures"]:
        lines += ["", "## Failed documents", ""] + [f"- {f['doc']}: {f['error']}" for f in summary["failures"]]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- dataset runner
def evaluate_dataset(data_dir: Path, kind: str = "digital",
                     extractor: Callable[[Path], ExtractedStatement] = extract_pdf) -> list[DocEval]:
    results: list[DocEval] = []
    for label_path in sorted(Path(data_dir).glob("*.json")):
        label = Label.model_validate_json(label_path.read_text(encoding="utf-8"))
        pdf = Path(data_dir) / (f"{label.doc_id}.pdf" if kind == "digital" else f"{label.doc_id}__{kind}.pdf")
        if not pdf.exists():
            continue
        try:
            results.append(evaluate_pair(label, extractor(pdf), kind))
        except Exception as exc:  # a failed document counts against the metrics, it is not hidden
            failed = DocEval(label.doc_id, label.layout, kind, truth_rows=len(label.statement.transactions),
                             error=f"{type(exc).__name__}: {exc}")
            fields = [f for f in ROW_FIELDS if f in label.fields_present]
            failed.row_total = {f: len(label.statement.transactions) for f in fields}
            failed.header_total = {f: 1 for f in HEADER_FIELDS}
            results.append(failed)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate extraction against synthetic ground truth.")
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--kind", default="digital", help="digital, scan_light, scan_medium or scan_heavy")
    parser.add_argument("--out", type=Path, default=None, help="directory for metrics.json and report.md")
    args = parser.parse_args()

    docs = evaluate_dataset(args.data, args.kind)
    if not docs:
        raise SystemExit(f"no documents of kind '{args.kind}' found in {args.data}")
    summary = summarize(docs)
    report = render_markdown(summary, args.kind)
    print(report)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (args.out / "report.md").write_text(report, encoding="utf-8")
        print(f"Wrote {args.out / 'metrics.json'} and {args.out / 'report.md'}")


if __name__ == "__main__":
    main()
