"""Inject OCR-style errors into correctly extracted statements and measure what review catches.

    python -m stmtai.robustness --data data/synthetic --errors 1,3,6,10

Extraction from digital PDFs is exact, so the confidence scoring would otherwise never be exercised.
This corrupts known fields by digit-sized amounts (the mistakes OCR makes: a dropped digit, a shifted
decimal point) and asks two questions:

* **field detection** - was the exact corrupted field flagged for review?
* **row detection**   - was its row flagged at all? This is what matters in practice, because the
  reviewer sees the whole row next to the page image.

It also reports how much work review costs: the share of all fields sent to a human.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .extract.digital import NotDigitalError, extract_digital
from .extract.scoring import review_items, score

# Digit-level corruptions: a wrong digit, a shifted decimal point, a dropped paise.
CORRUPTIONS = ["9.00", "-90.00", "900.00", "0.09", "-0.90", "1000.00"]


@dataclass
class RobustnessResult:
    errors_per_doc: int
    docs: int
    injected: int
    field_hits: int
    row_hits: int
    fields_flagged: int
    fields_total: int

    def as_dict(self) -> dict:
        def ratio(a: int, b: int) -> float | None:
            return round(a / b, 4) if b else None

        return {
            "errors_per_doc": self.errors_per_doc,
            "docs": self.docs,
            "injected_errors": self.injected,
            "field_detection": ratio(self.field_hits, self.injected),
            "row_detection": ratio(self.row_hits, self.injected),
            "fields_flagged": self.fields_flagged,
            "fields_total": self.fields_total,
            "review_load": ratio(self.fields_flagged, self.fields_total),
        }


def run(data_dir: Path, errors_per_doc: int, seed: int = 0, min_rows: int = 20) -> RobustnessResult:
    rng = random.Random(seed)
    result = RobustnessResult(errors_per_doc, 0, 0, 0, 0, 0, 0)

    for pdf in sorted(data_dir.glob("*.pdf")):
        if "__scan" in pdf.name:
            continue
        try:
            ext = extract_digital(pdf)
        except NotDigitalError:
            continue
        n = len(ext.transactions)
        if n < min_rows:
            continue
        result.docs += 1

        injected: set[tuple[int, str]] = set()
        for _ in range(errors_per_doc):
            k = rng.randrange(1, n - 1)
            txn = ext.transactions[k]
            amount_field = "debit" if txn.value("debit") is not None else "credit"
            target = rng.choice([amount_field, "balance"])
            fv = txn.fields.get(target)
            if fv is None or fv.value is None:
                continue
            fv.value += Decimal(rng.choice(CORRUPTIONS))
            injected.add((k, target))

        score(ext)
        flagged = {(r, f) for r, f, _, _ in review_items(ext) if r is not None}
        result.injected += len(injected)
        result.field_hits += len(injected & flagged)
        result.row_hits += len({r for r, _ in injected} & {r for r, _ in flagged})
        result.fields_flagged += len(flagged)
        result.fields_total += sum(len(t.fields) for t in ext.transactions)

    return result


def render_markdown(results: list[RobustnessResult]) -> str:
    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x * 100:.1f}%"

    lines = [
        "# Robustness: injected-error detection", "",
        "Digit-level errors are injected into correctly extracted statements, then the reconciliation-based",
        "confidence scoring is asked to find them. *Field* detection means the exact corrupted field was",
        "flagged; *row* detection means its row was flagged, which is what the reviewer actually sees.", "",
        "| Errors per doc | Injected | Field detection | Row detection | Fields sent to review |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        d = r.as_dict()
        lines.append(f"| {d['errors_per_doc']} | {d['injected_errors']} | {pct(d['field_detection'])} | "
                     f"{pct(d['row_detection'])} | {pct(d['review_load'])} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure injected-error detection.")
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--errors", default="1,3,6,10", help="comma-separated error counts per document")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    results = [run(args.data, int(k), args.seed) for k in args.errors.split(",")]
    if not any(r.docs for r in results):
        raise SystemExit(f"no digital PDFs with enough rows found in {args.data}")
    report = render_markdown(results)
    print(report)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "robustness.json").write_text(json.dumps([r.as_dict() for r in results], indent=2),
                                                  encoding="utf-8")
        (args.out / "robustness.md").write_text(report, encoding="utf-8")
        print(f"Wrote {args.out / 'robustness.json'} and {args.out / 'robustness.md'}")


if __name__ == "__main__":
    main()
