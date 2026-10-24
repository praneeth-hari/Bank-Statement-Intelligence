# Extraction report: `scan_heavy`

12 documents, 983 ground-truth rows. Row recall 55.2%, row precision 61.9%, **financial-field accuracy 34.9%** (date, debit, credit, balance), all-field accuracy 28.2%, header accuracy 11.7%, exact-match documents 0.0%. Free-text character accuracy: description 32.2%, ref 30.4%.

| Layout | Docs | Rows (truth / extracted) | Row recall | Row precision | Field accuracy | Header accuracy | Exact docs | Reconciles |
|---|---|---|---|---|---|---|---|---|
| classic_grid | 3 | 274 / 274 | 78.5% | 78.5% | 40.1% | 20.0% | 0.0% | 0.0% |
| drcr_single_amount | 3 | 230 / 228 | 33.9% | 34.2% | 14.7% | 16.7% | 0.0% | 0.0% |
| modern_zebra | 3 | 227 / 109 | 26.4% | 55.0% | 12.2% | 3.3% | 0.0% | 0.0% |
| wrapped_two_date | 3 | 252 / 266 | 75.4% | 71.4% | 36.2% | 6.7% | 0.0% | 0.0% |

## Accuracy by field (all layouts)

| Field | Accuracy |
|---|---|
| balance | 26.7% |
| credit | 48.4% |
| date | 25.8% |
| debit | 38.6% |
| description | 1.0% |
| ref | 26.2% |
| value_date | 34.5% |

## Header fields

| Field | Accuracy |
|---|---|
| account_holder | 8.3% |
| account_number | 0.0% |
| bank_name | 75.0% |
| branch | 0.0% |
| closing_balance | 8.3% |
| currency | 0.0% |
| ifsc | 0.0% |
| opening_balance | 8.3% |
| period_end | 8.3% |
| period_start | 8.3% |

## Human-review loop

Fields below the 0.90 confidence threshold are sent to review: 2255 of 2498 compared fields (90.3%). Wrong fields: 1487; caught by a flag: 1436 (error recall 96.6%, flag precision 63.7%).

## Balance-chain suggestions

182 corrections proposed; 36.8% correct overall, 62.5% of the 40 corroborated by a neighbouring row, 29.6% of the rest. Accepting every suggestion fixes 63 wrong fields and breaks 82 correct ones, taking row-field accuracy from 28.2% to 30.5%.

| Field | As read | After suggestions |
|---|---|---|
| balance | 26.7% | 31.6% |
| credit | 48.4% | 52.3% |
| date | 25.8% | 29.7% |
| debit | 38.6% | 40.4% |
| description | 1.0% | 1.2% |
| ref | 26.2% | 24.9% |
| value_date | 34.5% | 32.9% |

## Example errors

| Doc | Row | Field | Truth | Got |
|---|---|---|---|---|
| classic_grid_00 | 0 | description | NEFT-N724238849696532-ORBITAL SOFTWARE PVT LTD-SALARY | NEFNT242388A90SM512GRBITAESOFTWARE PVILTD SALARY |
| classic_grid_00 | 0 | ref | N724238849696532 | N724238849686532 |
| classic_grid_00 | 0 | credit | 68680.00 | 6888.00 |
| classic_grid_00 | 0 | balance | 183644.36 | 183644.35 |
| classic_grid_00 | 2 | description | UPI/691669784801/YASH KAPOOR | UIE91609S4SOIYASHKAPOXOR 洗 |
| classic_grid_00 | 2 | ref | 691669784801 | 691189784801 |
| classic_grid_00 | 2 | balance | 184243.76 | 1842.43 |
| classic_grid_00 | 3 | description | UPI/514627048281/HARSH CHAHAL | UPW51427MS18THARSHCHAHAL |
| classic_grid_00 | 3 | ref | 514627048281 | 5148272048281 |
| classic_grid_00 | 3 | debit | 5650.54 | 8650.54 |
| classic_grid_00 | 4 | date | 2025-04-03 | 2024-04-03 |
| classic_grid_00 | 4 | description | ATM WDL 893252 PATNA | ATMWOL83T252PANA |
| classic_grid_00 | 4 | balance | 176593.22 | 105393.22 |
| classic_grid_00 | 5 | description | UPI/809570154303/GIRIK KAMDAR | UPI/809570154323GIRIKKAMDAR |
| classic_grid_00 | 5 | ref | 809570154303 | 809-70154303 |

## Failed documents

- modern_zebra_00: ExtractionError: no transaction table header found on page 1 of modern_zebra_00__scan_heavy.pdf
- modern_zebra_05: ExtractionError: no transaction table header found on page 1 of modern_zebra_05__scan_heavy.pdf
