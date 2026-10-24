# Bank Statement Intelligence

Extract transactions from bank statements (digital PDFs and messy scans), score how much to trust
every field, and send only the uncertain ones to a human reviewer. Corrections feed an evaluation loop.

> **Status:** step 1 of 7 complete: synthetic data generator with exact ground truth.
> Extraction, confidence scoring, evaluation, API and review UI are next (see roadmap).

All data in this repository is **synthetic**. Banks, people, accounts and IFSC codes are fictional,
and every generated page is stamped as a sample. No real customer data is used or needed.

## Why synthetic data first

Evaluation needs ground truth. Because the generator knows every true value, the project can report
exact field-level accuracy per layout and per scan quality, which real statements would not allow
without manual labelling (and without handling personal data).

## What the generator produces

Four deliberately different layouts, each tied to a fictional bank:

| Layout | Page | Columns / quirks |
|---|---|---|
| `classic_grid` | A4 portrait | Full grid, Indian digit grouping (`1,23,456.00`), separate Ref column, wrapped refs |
| `modern_zebra` | A4 portrait | Zebra rows, `dd Mon yyyy` dates, western grouping, summary box that must be ignored |
| `drcr_single_amount` | A4 portrait | One amount column with `Dr`/`Cr` suffixes, balance suffixed `Cr` |
| `wrapped_two_date` | A4 landscape | Transaction + value dates, wrapped descriptions, opening/brought-forward/carried-forward/closing rows |

Every digital PDF can also be turned into **scans** (image-only PDFs, no text layer) at three severities:
`light` (flatbed), `medium` (phone photo, skew + perspective + uneven light), `heavy` (poor photocopy).

Each document gets a JSON label with the full statement, the layout name and which fields the layout prints.

## Quickstart

```bash
pip install -e ".[dev]"
python -m stmtai.synth.generate --out data/synthetic --per-layout 6 --seed 42
pytest
```

Output per document: `<id>.pdf`, `<id>.json` (ground truth), `<id>__scan_<severity>.pdf`, plus `manifest.csv`.
Small examples are committed under `samples/`.

## Reconciliation

`stmtai.reconcile.reconcile(statement)` checks that `previous balance + credit - debit == balance` on every row,
that the last balance equals the closing balance, and that dates are ordered and inside the statement period.
This is the strongest correctness signal for statements and will drive the per-field confidence score.

## Roadmap

1. [x] Synthetic statement generator with ground truth
2. [ ] Digital PDF extraction + reconciliation scoring
3. [ ] Scan path: cleanup, OCR with word confidence, table reconstruction
4. [ ] Confidence scoring + evaluation report (field accuracy by layout and scan quality)
5. [ ] FastAPI service
6. [ ] React review UI (page image with boxes, editable table, low-confidence cells highlighted)
7. [ ] LLM fallback for messy rows, natural-language query layer, Docker, demo video

## Layout of the repo

```
src/stmtai/
  schema.py        Pydantic models (Transaction, Statement, Label)
  reconcile.py     running-balance and date checks
  synth/           transactions, PDF layouts, scan degradation, dataset CLI
tests/             36 tests: reconciliation, determinism, PDF text vs ground truth, scans
samples/           a few generated documents
```
