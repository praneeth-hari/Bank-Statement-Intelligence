"""Per-field confidence from structure and from the running-balance chain.

The chain ``previous balance + credit - debit == balance`` is checked on every row, continuing from the
*stated* balance of each row. That makes the pattern of failures informative:

* row *i* breaks but row *i+1* is consistent  -> the balance of row *i* agrees with what follows, so the
  **amount** of row *i* is the likely error;
* rows *i* and *i+1* both break               -> the **balance** of row *i* is the likely error (the next row
  is measured from it), and its amount is only mildly suspect;
* the last row breaks                         -> amount and balance are equally suspect.

Fields flagged this way drop below ``REVIEW_THRESHOLD`` and go to the human review screen.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .models import ExtractedStatement, FieldValue

REVIEW_THRESHOLD = 0.90


def _lower(fv: Optional[FieldValue], confidence: float, flag: str) -> None:
    if fv is None:
        return
    fv.confidence = min(fv.confidence, confidence)
    if flag not in fv.flags:
        fv.flags.append(flag)


def _signed(t) -> Optional[Decimal]:
    debit, credit = t.value("debit"), t.value("credit")
    if (debit is None) == (credit is None):
        return None
    return credit if credit is not None else -debit


def score(ext: ExtractedStatement) -> ExtractedStatement:
    """Lower confidences in place and fill ``ext.issues``. Returns ``ext`` for chaining."""
    issues: list[dict] = []
    txns = ext.transactions
    n = len(txns)

    # 1) structural checks per row
    for i, t in enumerate(txns):
        for name in ("date", "balance"):
            fv = t.fields.get(name)
            if fv is None or fv.value is None:
                issues.append({"kind": "missing_field", "row": i, "field": name})
        has_debit = t.value("debit") is not None
        has_credit = t.value("credit") is not None
        if has_debit and has_credit:
            issues.append({"kind": "ambiguous_amount", "row": i, "field": "amount"})
            _lower(t.fields.get("debit"), 0.30, "both_debit_and_credit")
            _lower(t.fields.get("credit"), 0.30, "both_debit_and_credit")
        elif not has_debit and not has_credit:
            issues.append({"kind": "missing_amount", "row": i, "field": "amount"})
        for name, fv in t.fields.items():
            if fv.value is None and fv.text:
                issues.append({"kind": "unparseable", "row": i, "field": name, "text": fv.text})

    # 2) running-balance chain
    opening = ext.header_value("opening_balance")
    previous: Optional[Decimal] = opening
    bad: set[int] = set()
    checked: set[int] = set()
    delta: dict[int, Decimal] = {}  # actual balance minus the balance the chain predicts
    for i, t in enumerate(txns):
        balance, amount = t.value("balance"), _signed(t)
        if balance is None or amount is None or previous is None:
            previous = balance  # chain restarts from whatever balance we have
            continue
        checked.add(i)
        if previous + amount != balance:
            bad.add(i)
            delta[i] = balance - (previous + amount)
            issues.append({"kind": "balance_mismatch", "row": i, "expected": str(previous + amount),
                           "actual": str(balance)})
        previous = balance

    # Explain the breaks left to right with two templates: a wrong balance at row i breaks rows i and i+1
    # (the next row is measured from it); a wrong amount at row i breaks only row i.
    #
    # The two are told apart by arithmetic rather than guessed: if the balance of row i is off by d, it
    # inflates row i's own difference by +d and row i+1's by -d, so the pair must cancel exactly. Adjacent
    # breaks that do not cancel are two independent errors and are reported as such.
    broken = sorted(bad)
    k = 0
    while k < len(broken):
        i = broken[k]
        t = txns[i]
        amount_fields = [t.fields.get("debit"), t.fields.get("credit")]
        caused_by_this_balance = (i + 1) in bad and delta.get(i) == -delta.get(i + 1)
        if caused_by_this_balance:
            _lower(t.fields.get("balance"), 0.20, "balance_chain_break")
            for fv in amount_fields:
                _lower(fv, 0.60, "balance_chain_break")
            k += 2  # row i+1 is explained by row i's balance
        elif i == n - 1:
            _lower(t.fields.get("balance"), 0.30, "balance_chain_break")
            for fv in amount_fields:
                _lower(fv, 0.30, "balance_chain_break")
            k += 1
        else:
            for fv in amount_fields:
                _lower(fv, 0.20, "balance_chain_break")
            k += 1

    # 3) closing balance
    closing = ext.header_value("closing_balance")
    if txns and closing is not None and txns[-1].value("balance") is not None:
        if txns[-1].value("balance") != closing:
            issues.append({"kind": "closing_mismatch", "row": None, "expected": str(closing),
                           "actual": str(txns[-1].value("balance"))})
            # If the chain is intact to the last row, the printed closing balance is the odd one out;
            # either way the last balance and the closing balance cannot both be right.
            _lower(ext.header.get("closing_balance"), 0.30, "closing_mismatch")
            _lower(txns[-1].fields.get("balance"), 0.30, "closing_mismatch")

    # 4) dates
    last_date = None
    start, end = ext.header_value("period_start"), ext.header_value("period_end")
    for i, t in enumerate(txns):
        d = t.value("date")
        if d is None:
            continue
        if last_date is not None and d < last_date:
            issues.append({"kind": "date_order", "row": i, "field": "date"})
            _lower(t.fields.get("date"), 0.40, "date_out_of_order")
        if start and end and not (start <= d <= end):
            issues.append({"kind": "out_of_period", "row": i, "field": "date"})
            _lower(t.fields.get("date"), 0.40, "date_outside_period")
        last_date = max(last_date, d) if last_date else d

    ext.issues = issues
    flagged = review_items(ext)
    total_fields = sum(len(t.fields) for t in txns)
    ext.meta["summary"] = {
        "rows": n,
        "fields": total_fields,
        "fields_to_review": len(flagged),
        "rows_to_review": len({r for r, _, _, _ in flagged if r is not None}),
        "chain_rows_checked": len(checked),
        "chain_breaks": len(bad),
        "reconciles": not bad and not any(i["kind"] == "closing_mismatch" for i in issues),
    }
    return ext


def review_items(ext: ExtractedStatement, threshold: float = REVIEW_THRESHOLD) -> list[tuple[Optional[int], str, float, list[str]]]:
    """(row index or None for header fields, field name, confidence, flags) for everything below ``threshold``."""
    out = []
    for name, fv in ext.header.items():
        if fv.confidence < threshold:
            out.append((None, name, fv.confidence, fv.flags))
    for i, t in enumerate(ext.transactions):
        for name, fv in t.fields.items():
            if fv.confidence < threshold:
                out.append((i, name, fv.confidence, fv.flags))
    return out
