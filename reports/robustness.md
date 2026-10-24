# Robustness: injected-error detection

Digit-level errors are injected into correctly extracted statements, then the reconciliation-based
confidence scoring is asked to find them. *Field* detection means the exact corrupted field was
flagged; *row* detection means its row was flagged, which is what the reviewer actually sees.

| Errors per doc | Injected | Field detection | Row detection | Fields sent to review |
|---|---|---|---|---|
| 1 | 24 | 100.0% | 100.0% | 0.5% |
| 3 | 71 | 98.6% | 98.6% | 1.4% |
| 6 | 141 | 95.0% | 97.2% | 2.6% |
| 10 | 233 | 86.3% | 93.1% | 3.9% |
