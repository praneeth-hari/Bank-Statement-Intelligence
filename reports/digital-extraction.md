# Extraction report: `digital`

24 documents, 1689 ground-truth rows. Row recall 100.0%, row precision 100.0%, row-field accuracy 100.0%, header accuracy 100.0%, exact-match documents 100.0%.

| Layout | Docs | Rows (truth / extracted) | Row recall | Row precision | Field accuracy | Header accuracy | Exact docs | Reconciles |
|---|---|---|---|---|---|---|---|---|
| classic_grid | 6 | 431 / 431 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| drcr_single_amount | 6 | 417 / 417 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| modern_zebra | 6 | 411 / 411 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| wrapped_two_date | 6 | 430 / 430 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |

## Accuracy by field (all layouts)

| Field | Accuracy |
|---|---|
| balance | 100.0% |
| credit | 100.0% |
| date | 100.0% |
| debit | 100.0% |
| description | 100.0% |
| ref | 100.0% |
| value_date | 100.0% |

## Header fields

| Field | Accuracy |
|---|---|
| account_holder | 100.0% |
| account_number | 100.0% |
| bank_name | 100.0% |
| branch | 100.0% |
| closing_balance | 100.0% |
| currency | 100.0% |
| ifsc | 100.0% |
| opening_balance | 100.0% |
| period_end | 100.0% |
| period_start | 100.0% |

## Human-review loop

Fields below the 0.90 confidence threshold are sent to review: 0 of 8078 compared fields (0.0%). Wrong fields: 0; caught by a flag: 0 (error recall n/a, flag precision n/a).
