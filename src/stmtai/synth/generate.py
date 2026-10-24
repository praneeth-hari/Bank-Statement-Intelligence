"""Generate a synthetic dataset: digital PDFs, degraded scans and ground-truth labels.

    python -m stmtai.synth.generate --out data/synthetic --per-layout 6 --seed 42

For every document ``<doc_id>`` this writes:
    <doc_id>.pdf                      digital PDF with a text layer
    <doc_id>.json                     ground-truth label (statement + metadata)
    <doc_id>__scan_<severity>.pdf     image-only degraded scan(s)
and a ``manifest.csv`` listing everything.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import pymupdf

from ..schema import Label
from .layouts import LAYOUTS, render
from .scan import SEVERITIES, make_scan
from .transactions import generate_statement


def build_dataset(out_dir: Path, per_layout: int, seed: int, scans: bool = True) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []

    for layout_index, layout in enumerate(LAYOUTS):
        for k in range(per_layout):
            doc_seed = seed + layout_index * 1000 + k
            doc_id = f"{layout.name}_{k:02d}"
            months = 1 + (k % 3)
            statement = generate_statement(doc_seed, layout.bank, months=months)

            pdf_path = out_dir / f"{doc_id}.pdf"
            render(layout.name, statement, pdf_path)
            label = Label(doc_id=doc_id, layout=layout.name, seed=doc_seed,
                          fields_present=list(layout.fields), statement=statement)
            (out_dir / f"{doc_id}.json").write_text(label.model_dump_json(indent=2), encoding="utf-8")

            with pymupdf.open(pdf_path) as doc:
                pages = len(doc)

            severities: list[str] = []
            if scans:
                severities = list(SEVERITIES) if k == 0 else [SEVERITIES[k % len(SEVERITIES)]]
                for sev in severities:
                    make_scan(pdf_path, out_dir / f"{doc_id}__scan_{sev}.pdf", sev, seed=doc_seed + 7)

            manifest.append({
                "doc_id": doc_id, "layout": layout.name, "seed": doc_seed, "pages": pages,
                "transactions": len(statement.transactions), "months": months,
                "scans": "|".join(severities),
            })

    with (out_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(manifest[0].keys()))
        writer.writeheader()
        writer.writerows(manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic bank statements with ground truth.")
    parser.add_argument("--out", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--per-layout", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-scans", action="store_true")
    args = parser.parse_args()

    manifest = build_dataset(args.out, args.per_layout, args.seed, scans=not args.no_scans)
    total_txns = sum(m["transactions"] for m in manifest)
    print(f"Wrote {len(manifest)} documents ({total_txns} transactions) to {args.out}")


if __name__ == "__main__":
    main()
