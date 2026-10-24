# Extraction report: `scan_medium`

12 documents, 696 ground-truth rows. Row recall 11.2%, row precision 81.2%, **financial-field accuracy 8.7%** (date, debit, credit, balance), all-field accuracy 9.0%, header accuracy 14.2%, exact-match documents 0.0%. Free-text character accuracy: description 46.0%, ref 47.9%.

| Layout | Docs | Rows (truth / extracted) | Row recall | Row precision | Field accuracy | Header accuracy | Exact docs | Reconciles |
|---|---|---|---|---|---|---|---|---|
| classic_grid | 3 | 170 / 0 | 0.0% | n/a | 0.0% | 0.0% | 0.0% | 0.0% |
| drcr_single_amount | 3 | 179 / 0 | 0.0% | n/a | 0.0% | 0.0% | 0.0% | 0.0% |
| modern_zebra | 3 | 169 / 30 | 9.5% | 53.3% | 4.5% | 33.3% | 0.0% | 0.0% |
| wrapped_two_date | 3 | 178 / 66 | 34.8% | 93.9% | 25.9% | 23.3% | 0.0% | 0.0% |

## Accuracy by field (all layouts)

| Field | Accuracy |
|---|---|
| balance | 9.8% |
| credit | 10.6% |
| date | 7.3% |
| debit | 6.9% |
| description | 5.0% |
| ref | 10.3% |
| value_date | 27.5% |

## Header fields

| Field | Accuracy |
|---|---|
| account_holder | 8.3% |
| account_number | 8.3% |
| bank_name | 16.7% |
| branch | 16.7% |
| closing_balance | 16.7% |
| currency | 16.7% |
| ifsc | 16.7% |
| opening_balance | 8.3% |
| period_end | 16.7% |
| period_start | 16.7% |

## Human-review loop

Fields below the 0.90 confidence threshold are sent to review: 107 of 393 compared fields (27.2%). Wrong fields: 95; caught by a flag: 55 (error recall 57.9%, flag precision 51.4%).

## Balance-chain suggestions

28 corrections proposed; 53.6% correct overall, 60.0% of the 10 corroborated by a neighbouring row, 50.0% of the rest. Accepting every suggestion fixes 15 wrong fields and breaks 5 correct ones, taking row-field accuracy from 9.0% to 60.7%.

| Field | As read | After suggestions |
|---|---|---|
| balance | 9.8% | 79.6% |
| credit | 10.6% | 81.7% |
| date | 7.3% | 46.2% |
| debit | 6.9% | 74.2% |
| description | 5.0% | 29.0% |
| ref | 10.3% | 47.7% |
| value_date | 27.5% | 63.1% |

## Example errors

| Doc | Row | Field | Truth | Got |
|---|---|---|---|---|
| modern_zebra_00 | 1 | date | 2025-08-02 | None |
| modern_zebra_00 | 1 | description | UPI/324563730275/MADHAV PANT | None |
| modern_zebra_00 | 5 | date | 2025-08-07 | None |
| modern_zebra_00 | 5 | description | ATM WDL 920483 KATNI | None |
| modern_zebra_00 | 5 | debit | 1000.00 | None |
| modern_zebra_00 | 10 | date | 2025-08-12 | None |
| modern_zebra_00 | 10 | description | UPI/727843111030/IRCTC | None |
| modern_zebra_00 | 10 | debit | 3450.00 | None |
| modern_zebra_00 | 11 | date | 2025-08-14 | None |
| modern_zebra_00 | 11 | description | ATM WDL 681900 GUNA | None |
| modern_zebra_00 | 11 | debit | 1000.00 | None |
| modern_zebra_00 | 14 | date | 2025-08-16 | None |
| modern_zebra_00 | 14 | description | UPI/276800290153/DHRUV PARMAR | None |
| modern_zebra_00 | 14 | debit | 4042.58 | None |
| modern_zebra_00 | 16 | date | 2025-08-20 | None |

## Failed documents

- classic_grid_00: ExtractionError: no transaction table header found on page 1 of classic_grid_00__scan_medium.pdf
- classic_grid_01: ExtractionError: no transaction table header found on page 1 of classic_grid_01__scan_medium.pdf
- classic_grid_04: ExtractionError: no transaction table header found on page 1 of classic_grid_04__scan_medium.pdf
- drcr_single_amount_00: ExtractionError: no transaction table header found on page 1 of drcr_single_amount_00__scan_medium.pdf
- drcr_single_amount_01: ExtractionError: no transaction table header found on page 1 of drcr_single_amount_01__scan_medium.pdf
- drcr_single_amount_04: ExtractionError: no transaction table header found on page 1 of drcr_single_amount_04__scan_medium.pdf
- modern_zebra_01: ExtractionError: no transaction table header found on page 1 of modern_zebra_01__scan_medium.pdf
- modern_zebra_04: ExtractionError: no transaction table header found on page 1 of modern_zebra_04__scan_medium.pdf
- wrapped_two_date_00: ExtractionError: no transaction table header found on page 1 of wrapped_two_date_00__scan_medium.pdf
- wrapped_two_date_04: ExtractionError: no transaction table header found on page 1 of wrapped_two_date_04__scan_medium.pdf
