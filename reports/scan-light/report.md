# Extraction report: `scan_light`

8 documents, 292 ground-truth rows. Row recall 100.0%, row precision 100.0%, **financial-field accuracy 100.0%** (date, debit, credit, balance), all-field accuracy 99.6%, header accuracy 100.0%, exact-match documents 50.0%. Free-text character accuracy: description 99.9%, ref 100.0%.

| Layout | Docs | Rows (truth / extracted) | Row recall | Row precision | Field accuracy | Header accuracy | Exact docs | Reconciles |
|---|---|---|---|---|---|---|---|---|
| classic_grid | 2 | 73 / 73 | 100.0% | 100.0% | 99.8% | 100.0% | 50.0% | 100.0% |
| drcr_single_amount | 2 | 68 / 68 | 100.0% | 100.0% | 99.7% | 100.0% | 50.0% | 100.0% |
| modern_zebra | 2 | 71 / 71 | 100.0% | 100.0% | 99.4% | 100.0% | 50.0% | 100.0% |
| wrapped_two_date | 2 | 80 / 80 | 100.0% | 100.0% | 99.5% | 100.0% | 50.0% | 100.0% |

## Accuracy by field (all layouts)

| Field | Accuracy |
|---|---|
| balance | 100.0% |
| credit | 100.0% |
| date | 100.0% |
| debit | 100.0% |
| description | 97.6% |
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

Fields below the 0.90 confidence threshold are sent to review: 97 of 1444 compared fields (6.7%). Wrong fields: 7; caught by a flag: 2 (error recall 28.6%, flag precision 2.1%).

## Example errors

| Doc | Row | Field | Truth | Got |
|---|---|---|---|---|
| classic_grid_00 | 29 | description | UPI/482366299468/KRITIKA BRAR | UPI/482366299468/KR/TIKABRAR |
| drcr_single_amount_03 | 5 | description | UPI/010328570385/VRITTI JAIN | UPI/010328570385/NRITTIJAIN |
| modern_zebra_03 | 1 | description | IMPS/414451545617/ISHWAR SHROFF | IMPS/414451545617/SHWARSHROFF |
| modern_zebra_03 | 16 | description | UPI/861884036469/AYUSH SRIVASTAVA | UPI/861884036469/AYUSHSR/VASTAVA |
| wrapped_two_date_00 | 21 | description | UPI/147733451770/BLINKIT | UPI/147733451770/BLINK/T |
| wrapped_two_date_00 | 28 | description | POS BLINKIT HUBLI–DHARWAD | POSBLINKITHUBLI-DHARWAD |
| wrapped_two_date_00 | 35 | description | UPI/468538331406/MYNTRA | UP//468538331406/MYNTRA |
