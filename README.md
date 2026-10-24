# Bank Statement Intelligence

Extract transactions from bank statements (digital PDFs and messy scans), score how much to trust
every field, and send only the uncertain ones to a human reviewer. Corrections feed an evaluation loop.

> **Status:** steps 1-2 of 7 complete: synthetic data with ground truth, digital-PDF extraction,
> reconciliation-based confidence scoring, and an evaluation harness. OCR, API and review UI are next.

All data in this repository is **synthetic**. Banks, people, accounts and IFSC codes are fictional,
and every generated page is stamped as a sample. No real customer data is used or needed.

## Results

Digital PDFs, 24 documents, 1,689 transactions, 4 layouts — reproduce with
`python -m stmtai.evaluate --data data/synthetic --kind digital`:

| Metric | Result |
|---|---|
| Row recall / precision | 100% / 100% |
| Transaction field accuracy | 100% (7,838 fields) |
| Account-field accuracy | 100% (240 fields) |
| Documents extracted exactly | 100% |

Extraction is exact because these PDFs carry a reliable text layer, so the number that matters is the
one below: whether the confidence scoring finds errors once they exist. `python -m stmtai.robustness`
corrupts known-correct fields by digit-sized amounts and asks the scorer to find them.

| Errors per doc | Injected | Field detection | Row detection | Fields sent to review |
|---|---|---|---|---|
| 1 | 24 | 100.0% | 100.0% | 0.5% |
| 3 | 71 | 98.6% | 98.6% | 1.4% |
| 6 | 141 | 95.0% | 97.2% | 2.6% |
| 10 | 233 | 86.3% | 93.1% | 3.9% |

Reading this: with a realistic error rate, a reviewer checks **under 2% of fields** and sees
**98-99% of the errors**. Detection degrades as errors crowd together, which is the honest result —
see *Known limitations*.

## How confidence works

The running balance is the strongest correctness signal a statement has:
`previous balance + credit - debit` must equal the printed balance on every row. The chain continues
from each row's *stated* balance, so one bad row does not poison every row after it, and the **pattern**
of breaks localizes the error by arithmetic rather than guesswork:

- a balance wrong by `d` inflates its own row's difference by `+d` and the next row's by `-d`, so an
  adjacent pair that **cancels exactly** means the first row's *balance* is wrong;
- adjacent breaks that do **not** cancel are two independent errors, reported separately;
- a lone break means that row's *amount* is wrong;
- a break on the last row is genuinely ambiguous, so both fields are flagged.

Dates are checked for ordering and against the statement period. Anything scoring below `0.90` goes to
human review. Every field keeps its bounding box, so the review UI can highlight it on the page image.

## Known limitations

- **Two consecutive wrong balances** defeat exact-field attribution: the deltas no longer cancel, so both
  rows are blamed on their amount instead. The rows are still flagged, which is why row detection stays
  above field detection in the table.
- **Compensating errors are invisible.** If an amount and a balance are wrong by the same amount in the
  same direction, the chain still closes. No arithmetic check can catch this; only OCR confidence or a
  second reading can.
- Extraction currently requires a text layer. Scans raise `NotDigitalError` until step 3.

## Quickstart

```bash
pip install -e ".[dev]"
python -m stmtai.synth.generate --out data/synthetic --per-layout 6 --seed 42
python -m stmtai.evaluate   --data data/synthetic --kind digital --out data/runs/digital
python -m stmtai.robustness --data data/synthetic --out data/runs/digital
pytest
```

```python
from stmtai.extract.pipeline import extract_pdf
from stmtai.extract.scoring import review_items

ext = extract_pdf("samples/classic_grid_00.pdf")
print(ext.meta["summary"])          # rows, chain breaks, whether it reconciles
for row, field, conf, flags in review_items(ext):
    print(row, field, conf, flags)  # what a human needs to check
```

## The synthetic data

Evaluation needs ground truth. Because the generator knows every true value, the project reports exact
field-level accuracy per layout and per scan quality — which real statements could not give without
manual labelling, and without handling personal data.

Four deliberately different layouts, each tied to a fictional bank:

| Layout | Page | Columns / quirks |
|---|---|---|
| `classic_grid` | A4 portrait | Full grid, Indian digit grouping (`1,23,456.00`), separate Ref column, wrapped refs |
| `modern_zebra` | A4 portrait | Zebra rows, `dd Mon yyyy` dates, western grouping, summary box that must be ignored |
| `drcr_single_amount` | A4 portrait | One amount column with `Dr`/`Cr` suffixes, balance suffixed `Cr` |
| `wrapped_two_date` | A4 landscape | Transaction + value dates, wrapped descriptions, opening/brought-forward/carried-forward/closing rows |

Every digital PDF can also be turned into **scans** (image-only PDFs, no text layer) at three severities:
`light` (flatbed), `medium` (phone photo, skew + perspective + uneven light), `heavy` (poor photocopy).

## How extraction works

No layout-specific code. The extractor finds the table header band, turns each header cell into a column,
and assigns every later word to a column by its x position. A line with a date in the date column starts a
transaction; a line with neither date nor amount is a wrapped continuation; a line with amounts but no date
is a marker (opening / carried-forward / closing). Single `Amount` columns are resolved to debit or credit
from the direction the balance moved, and `Dr`/`Cr` suffixes are honoured where present.

This generalizes: adding a fifth layout should need no new code, and the evaluation harness will say
whether that held.

## Roadmap

1. [x] Synthetic statement generator with ground truth
2. [x] Digital extraction, confidence scoring, evaluation + robustness harness
3. [ ] Scan path: cleanup, OCR with word confidence, table reconstruction
4. [ ] Benchmark OCR engines against each other on the same labelled scans
5. [ ] FastAPI service
6. [ ] React review UI (page image with boxes, editable table, low-confidence cells highlighted)
7. [ ] LLM fallback for messy rows, natural-language query layer, Docker, demo video

## Layout of the repo

```
src/stmtai/
  schema.py        Pydantic models (Transaction, Statement, Label)
  reconcile.py     running-balance and date checks
  evaluate.py      row alignment, per-field accuracy, review-loop metrics, report CLI
  robustness.py    injected-error detection harness
  extract/
    digital.py     text-layer extraction (header band, columns, rows, markers)
    scoring.py     per-field confidence from the balance chain
    parse.py       date and money parsing
    models.py      extraction output with bounding boxes and confidences
  synth/           transactions, PDF layouts, scan degradation, dataset CLI
tests/             71 tests, including negative controls for the evaluator itself
samples/           a few generated documents
reports/           committed output of the evaluation and robustness runs
```
