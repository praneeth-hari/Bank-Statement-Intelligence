# Extraction report: `scan_heavy`

12 documents, 983 ground-truth rows. Row recall 0.0%, row precision n/a, **financial-field accuracy 0.0%** (date, debit, credit, balance), all-field accuracy 0.0%, header accuracy 0.0%, exact-match documents 0.0%. Free-text character accuracy: .

| Layout | Docs | Rows (truth / extracted) | Row recall | Row precision | Field accuracy | Header accuracy | Exact docs | Reconciles |
|---|---|---|---|---|---|---|---|---|
| classic_grid | 3 | 274 / 0 | 0.0% | n/a | 0.0% | 0.0% | 0.0% | 0.0% |
| drcr_single_amount | 3 | 230 / 0 | 0.0% | n/a | 0.0% | 0.0% | 0.0% | 0.0% |
| modern_zebra | 3 | 227 / 0 | 0.0% | n/a | 0.0% | 0.0% | 0.0% | 0.0% |
| wrapped_two_date | 3 | 252 / 0 | 0.0% | n/a | 0.0% | 0.0% | 0.0% | 0.0% |

## Accuracy by field (all layouts)

| Field | Accuracy |
|---|---|
| balance | 0.0% |
| credit | 0.0% |
| date | 0.0% |
| debit | 0.0% |
| description | 0.0% |
| ref | 0.0% |
| value_date | 0.0% |

## Header fields

| Field | Accuracy |
|---|---|
| account_holder | 0.0% |
| account_number | 0.0% |
| bank_name | 0.0% |
| branch | 0.0% |
| closing_balance | 0.0% |
| currency | 0.0% |
| ifsc | 0.0% |
| opening_balance | 0.0% |
| period_end | 0.0% |
| period_start | 0.0% |

## Human-review loop

Fields below the 0.90 confidence threshold are sent to review: 0 of 0 compared fields (n/a). Wrong fields: 0; caught by a flag: 0 (error recall n/a, flag precision n/a).

## Failed documents

- classic_grid_00: ExtractionError: no transaction table header found on page 1 of classic_grid_00__scan_heavy.pdf
- classic_grid_02: ExtractionError: no transaction table header found on page 1 of classic_grid_02__scan_heavy.pdf
- classic_grid_05: ExtractionError: no transaction table header found on page 1 of classic_grid_05__scan_heavy.pdf
- drcr_single_amount_00: ExtractionError: no transaction table header found on page 1 of drcr_single_amount_00__scan_heavy.pdf
- drcr_single_amount_02: ExtractionError: no transaction table header found on page 1 of drcr_single_amount_02__scan_heavy.pdf
- drcr_single_amount_05: ExtractionError: no transaction table header found on page 1 of drcr_single_amount_05__scan_heavy.pdf
- modern_zebra_00: ExtractionError: no transaction table header found on page 1 of modern_zebra_00__scan_heavy.pdf
- modern_zebra_02: ExtractionError: no transaction table header found on page 1 of modern_zebra_02__scan_heavy.pdf
- modern_zebra_05: ExtractionError: no transaction table header found on page 1 of modern_zebra_05__scan_heavy.pdf
- wrapped_two_date_00: ExtractionError: no transaction table header found on page 1 of wrapped_two_date_00__scan_heavy.pdf
- wrapped_two_date_02: ExtractionError: no transaction table header found on page 1 of wrapped_two_date_02__scan_heavy.pdf
- wrapped_two_date_05: ExtractionError: no transaction table header found on page 1 of wrapped_two_date_05__scan_heavy.pdf
