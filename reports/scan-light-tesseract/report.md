# Extraction report: `scan_light`

8 documents, 292 ground-truth rows. Row recall 92.8%, row precision 88.3%, **financial-field accuracy 83.7%** (date, debit, credit, balance), all-field accuracy 84.2%, header accuracy 96.2%, exact-match documents 12.5%. Free-text character accuracy: description 83.1%, ref 90.2%.

| Layout | Docs | Rows (truth / extracted) | Row recall | Row precision | Field accuracy | Header accuracy | Exact docs | Reconciles |
|---|---|---|---|---|---|---|---|---|
| classic_grid | 2 | 73 / 73 | 100.0% | 100.0% | 97.3% | 100.0% | 0.0% | 50.0% |
| drcr_single_amount | 2 | 68 / 68 | 100.0% | 100.0% | 100.0% | 95.0% | 50.0% | 100.0% |
| modern_zebra | 2 | 71 / 51 | 70.4% | 98.0% | 55.8% | 100.0% | 0.0% | 0.0% |
| wrapped_two_date | 2 | 80 / 115 | 100.0% | 69.6% | 82.3% | 90.0% | 0.0% | 0.0% |

## Accuracy by field (all layouts)

| Field | Accuracy |
|---|---|
| balance | 76.7% |
| credit | 90.1% |
| date | 84.2% |
| debit | 83.9% |
| description | 80.5% |
| ref | 89.5% |
| value_date | 93.8% |

## Header fields

| Field | Accuracy |
|---|---|
| account_holder | 100.0% |
| account_number | 87.5% |
| bank_name | 100.0% |
| branch | 100.0% |
| closing_balance | 87.5% |
| currency | 100.0% |
| ifsc | 100.0% |
| opening_balance | 87.5% |
| period_end | 100.0% |
| period_start | 100.0% |

## Human-review loop

Fields below the 0.90 confidence threshold are sent to review: 194 of 1243 compared fields (15.6%). Wrong fields: 45; caught by a flag: 42 (error recall 93.3%, flag precision 21.6%).

## Balance-chain suggestions

14 corrections proposed; 92.9% correct overall, 90.9% of the 11 corroborated by a neighbouring row, 100.0% of the rest. Accepting every suggestion fixes 13 wrong fields and breaks 1 correct ones, taking row-field accuracy from 84.2% to 84.9%.

| Field | As read | After suggestions |
|---|---|---|
| balance | 76.7% | 81.2% |
| credit | 90.1% | 90.1% |
| date | 84.2% | 84.2% |
| debit | 83.9% | 83.6% |
| description | 80.5% | 80.5% |
| ref | 89.5% | 89.5% |
| value_date | 93.8% | 93.8% |

## Example errors

| Doc | Row | Field | Truth | Got |
|---|---|---|---|---|
| classic_grid_00 | 0 | description | NEFT-N724238849696532-ORBITAL SOFTWARE PVT LTD-SALARY | NEFT-N724238849696532-ORBITAL SOFTWARE PVT LTD-SALARY | |
| classic_grid_00 | 0 | ref | N724238849696532 | N724238849696534 |
| classic_grid_00 | 6 | description | UPI/171822782489/IRCTC | ib UPI/171822782489/IRCTC |
| classic_grid_00 | 13 | description | ATM WDL 132677 KISHANGANJ | ATM WDL 132677 KISHANGANJ | |
| classic_grid_00 | 28 | balance | 105483.05 | 1105483.05 |
| classic_grid_00 | 35 | ref | None | aa |
| classic_grid_00 | 40 | ref | None | | |
| classic_grid_00 | 41 | description | UPI/053100330923/HARRISON RAI | UPI/053100330923/HARRISON RAI | |
| classic_grid_03 | 6 | description | IMPS/688069079039/VEDA APTE | if IMPS/688069079039/VEDA APTE |
| classic_grid_03 | 23 | description | POS BOOKMYSHOW BULANDSHAHR | POS BOOKMYSHOW BULANDSHAHR: |
| classic_grid_03 | 26 | ref | 343220274789 | 3432202747891 |
| classic_grid_03 | 29 | ref | None | | |
| drcr_single_amount_03 | None | account_number | 811095294033229 | None |
| modern_zebra_00 | 1 | balance | 128292.03 | None |
| modern_zebra_00 | 2 | balance | 127527.23 | None |
