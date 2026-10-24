"""Choose a per-field review threshold on held-out data.

Run on a dataset generated with a different seed from the one results are reported on:

    python -m stmtai.synth.generate --out data/calibration --per-layout 3 --seed 9000
    python -m stmtai.calibrate --data data/calibration --field description

Prints, for each candidate threshold, how many fields a reviewer would have to open (review load) against how
many of the wrong fields that catches (error recall). Picking the point is a product decision; this makes the
trade-off visible instead of hiding it in a constant.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .evaluate import evaluate_dataset

CANDIDATES = (0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95)


def sweep(pairs: list[tuple[str, float, bool]], field: str, candidates=CANDIDATES) -> list[dict]:
    fp = [p for p in pairs if p[0] == field]
    wrong = [p for p in fp if not p[2]]
    rows = []
    for t in candidates:
        flagged = [p for p in fp if p[1] < t]
        caught = [p for p in wrong if p[1] < t]
        rows.append({"threshold": t, "n": len(fp), "wrong": len(wrong),
                     "review_load": len(flagged) / len(fp) if fp else 0.0,
                     "error_recall": len(caught) / len(wrong) if wrong else None})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=Path("data/calibration"))
    ap.add_argument("--field", default="description")
    ap.add_argument("--kinds", nargs="+", default=["scan_light", "scan_medium"])
    args = ap.parse_args()
    pairs: list[tuple[str, float, bool]] = []
    for kind in args.kinds:
        for d in evaluate_dataset(args.data, kind):
            pairs += d.conf_pairs
    print(f"field={args.field}  kinds={','.join(args.kinds)}  data={args.data}")
    print("threshold | review load | error recall | wrong/n")
    for r in sweep(pairs, args.field):
        rec = "n/a" if r["error_recall"] is None else f"{r['error_recall']:.1%}"
        print(f"   {r['threshold']:.2f}   |   {r['review_load']:6.1%}    |   {rec:>6}     | {r['wrong']}/{r['n']}")


if __name__ == "__main__":
    main()
