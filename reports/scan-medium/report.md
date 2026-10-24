# Extraction report: `scan_medium`

12 documents, 696 ground-truth rows. Row recall 100.0%, row precision 100.0%, **financial-field accuracy 99.6%** (date, debit, credit, balance), all-field accuracy 97.8%, header accuracy 87.5%, exact-match documents 0.0%. Free-text character accuracy: description 99.5%, ref 100.0%.

| Layout | Docs | Rows (truth / extracted) | Row recall | Row precision | Field accuracy | Header accuracy | Exact docs | Reconciles |
|---|---|---|---|---|---|---|---|---|
| classic_grid | 3 | 170 / 170 | 100.0% | 100.0% | 98.2% | 100.0% | 0.0% | 66.7% |
| drcr_single_amount | 3 | 179 / 179 | 100.0% | 100.0% | 97.2% | 93.3% | 0.0% | 66.7% |
| modern_zebra | 3 | 169 / 169 | 100.0% | 100.0% | 98.1% | 83.3% | 0.0% | 66.7% |
| wrapped_two_date | 3 | 178 / 178 | 100.0% | 100.0% | 97.6% | 73.3% | 0.0% | 66.7% |

## Accuracy by field (all layouts)

| Field | Accuracy |
|---|---|
| balance | 99.6% |
| credit | 100.0% |
| date | 99.0% |
| debit | 100.0% |
| description | 88.6% |
| ref | 100.0% |
| value_date | 100.0% |

## Header fields

| Field | Accuracy |
|---|---|
| account_holder | 75.0% |
| account_number | 41.7% |
| bank_name | 100.0% |
| branch | 91.7% |
| closing_balance | 100.0% |
| currency | 100.0% |
| ifsc | 91.7% |
| opening_balance | 91.7% |
| period_end | 91.7% |
| period_start | 91.7% |

## Human-review loop

Fields below the 0.90 confidence threshold are sent to review: 464 of 3337 compared fields (13.9%). Wrong fields: 92; caught by a flag: 68 (error recall 73.9%, flag precision 14.7%).

## Balance-chain suggestions

3 corrections proposed; 100.0% correct overall, 100.0% of the 3 corroborated by a neighbouring row, n/a of the rest. Accepting every suggestion fixes 3 wrong fields and breaks 0 correct ones, taking row-field accuracy from 97.8% to 97.9%.

| Field | As read | After suggestions |
|---|---|---|
| balance | 99.6% | 100.0% |
| credit | 100.0% | 100.0% |
| date | 99.0% | 99.0% |
| debit | 100.0% | 100.0% |
| description | 88.6% | 88.6% |
| ref | 100.0% | 100.0% |
| value_date | 100.0% | 100.0% |

## Example errors

| Doc | Row | Field | Truth | Got |
|---|---|---|---|---|
| classic_grid_00 | 0 | description | NEFT-N724238849696532-ORBITAL SOFTWARE PVT LTD-SALARY | NEFT-N724238849696532-ORBITAL.SOFTWARE PVTLTD-SALARY |
| classic_grid_00 | 25 | description | UPI/160733754330/GEORGE RAI | UPI/60733754330/GEORGERAI |
| classic_grid_00 | 26 | description | UPI/145868501429/JAGRATI PADMANABHAN | UPI/45868501429/JAGRATIPADMANABHAN |
| classic_grid_00 | 27 | description | UPI/965569816934/RELIANCE SMART | UPI/965569816934/RELIANCE.SMART |
| classic_grid_00 | 28 | description | UPI/835615951484/CALEB SHARAF | UPI/835615951484/CALEB:SHARAF |
| classic_grid_01 | 39 | description | UPI/435967919031/IRCTC | UPI/435967919031/RCTC |
| classic_grid_01 | 44 | description | UPI/128063678229/IRCTC | UPI/28063678229/RCTC |
| classic_grid_01 | 46 | description | UPI/124474807505/GEETIKA DANI | UPI/24474807505/GEETIKADANI |
| classic_grid_01 | 47 | description | UPI/041934904630/IRCTC | UPI/041934904630/RCTC |
| classic_grid_01 | 62 | description | IMPS/918071931008/VIVAAN MITAL | IMPS/91807193100B/VINAANMITAL |
| classic_grid_01 | 66 | description | UPI/848283661547/LOPA KAR | UPI/848283661547/LOPA.KAR |
| classic_grid_01 | 68 | description | UPI/441127501745/GOPAL BALA | UPV44.1127501745/GOPALBALA |
| classic_grid_04 | 0 | description | NEFT-N744803095640987-ORBITAL SOFTWARE PVT LTD-SALARY | NEFT-N744803095640987-ORBITALSOFTWARE PVTLTD.SALARY |
| classic_grid_04 | 5 | description | UPI/913622160591/SPOTIFY | UPI/9136221605.91/SPOTIFY |
| classic_grid_04 | 17 | description | UPI/558256922525/IMARAN SANT | UPI/558256922525/MARANSANT |
