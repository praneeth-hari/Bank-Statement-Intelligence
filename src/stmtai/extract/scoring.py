"""Per-field confidence and correction suggestions from structure and the running-balance chain.

The chain ``previous balance + credit - debit == balance`` is checked on every row, continuing from the
*stated* balance of each row.

**Verification.** A row whose arithmetic closes verifies its amount, its balance and the previous balance:
a misread that still balances the chain is vanishingly unlikely. On scans this is what separates trustworthy
cells from doubtful ones, because raw OCR confidence alone is poorly calibrated (correct cells routinely
score ~0.85).

**Localization.** The pattern of breaks says which field is wrong:

* a lone break at row *i*                     -> the **amount** of row *i*;
* breaks at *i* and *i+1* that cancel exactly -> the **balance** of row *i* (off by *d*, it shifts its own
  row by *+d* and the next by *-d*);
* adjacent breaks that do not cancel          -> two independent errors;
* a break on the last row                     -> decided by the printed closing balance when there is one.

**Suggestions.** Wherever the arithmetic pins down the right value, it is attached as ``suggestion`` - the
value as read is never overwritten. ``suggestion_verified`` means a neighbouring row corroborates it.
Unreadable cells get suggestions the same way, so a gap does not break the chain.

Fields below ``REVIEW_THRESHOLD`` go to the human review screen.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .models import ExtractedStatement, ExtractedTransaction, FieldValue

REVIEW_THRESHOLD = 0.90
# Per-field overrides. Free text is judged on a looser bar than numbers: OCR confidence is the only signal
# available for it, so a 0.90 cut sends most descriptions to a human for little gain. The value below was
# chosen on a held-out calibration set (data/calibration, a different seed from the reported results);
# see `python -m stmtai.calibrate`.
REVIEW_THRESHOLDS: dict[str, float] = {"description": 0.80}
VERIFIED_CONF = 0.98
ORDER_VERIFIED_CONF = 0.92  # weaker evidence than a closed balance equation, so it sits just above the threshold
MAX_VALUE_DATE_LAG_DAYS = 5  # a value date follows its transaction date by a few days at most


def threshold_for(name: str) -> float:
    return REVIEW_THRESHOLDS.get(name, REVIEW_THRESHOLD)


def _lower(fv: Optional[FieldValue], confidence: float, flag: str) -> None:
    if fv is None:
        return
    fv.confidence = min(fv.confidence, confidence)
    if flag not in fv.flags:
        fv.flags.append(flag)


def _verify(fv: Optional[FieldValue]) -> None:
    if fv is None or fv.value is None:
        return
    fv.confidence = max(fv.confidence, VERIFIED_CONF)
    if "chain_verified" not in fv.flags:
        fv.flags.append("chain_verified")


def _signed(t: ExtractedTransaction) -> Optional[Decimal]:
    debit, credit = t.value("debit"), t.value("credit")
    if (debit is None) == (credit is None):
        return None
    return credit if credit is not None else -debit


def _amount_field(t: ExtractedTransaction) -> Optional[FieldValue]:
    for name in ("debit", "credit"):
        fv = t.fields.get(name)
        if fv is not None and fv.value is not None:
            return fv
    return None


def _suggest(fv: FieldValue, value, verified: bool) -> None:
    fv.suggestion = value
    if verified and "suggestion_verified" not in fv.flags:
        fv.flags.append("suggestion_verified")


MAX_OCR_EDITS = 2  # a misread changes a character or two; a different amount entirely is not a misread


def _digit_string(value: Decimal) -> str:
    return f"{abs(value):.2f}".replace(".", "")


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _ocr_plausible(read: Optional[Decimal], suggested: Decimal) -> bool:
    """Could ``suggested`` be what the page says, given OCR read ``read``? Nothing read means nothing to contradict."""
    if read is None:
        return True
    return edit_distance(_digit_string(read), _digit_string(suggested)) <= MAX_OCR_EDITS


def _suggest_amount(t: ExtractedTransaction, implied: Decimal, verified: bool) -> bool:
    """Attach the amount implied by the balances to the correct side; ask to clear the wrong side.

    Returns False, attaching nothing, when the implied amount is not a plausible misreading of what was read:
    a single broken equation fits a misread amount, but it fits a dropped or merged row just as well, and a
    dropped row changes the amount by an arbitrary figure rather than by a digit or two.
    """
    read = _amount_field(t)
    if read is not None and not _ocr_plausible(read.value, abs(implied)):
        _lower(read, 0.20, "balance_chain_break")
        if "implausible_correction" not in read.flags:
            read.flags.append("implausible_correction")
        return False
    side, other = ("debit", "credit") if implied < 0 else ("credit", "debit")
    target = t.fields.get(side)
    if target is None:
        t.fields[side] = target = FieldValue(text="", value=None, confidence=0.0, source="inferred")
    _lower(target, 0.20 if target.value is not None else 0.0, "balance_chain_break")
    _suggest(target, abs(implied), verified)
    wrong = t.fields.get(other)
    if wrong is not None and wrong.value is not None:
        _lower(wrong, 0.20, "balance_chain_break")
        if "suggest_clear" not in wrong.flags:
            wrong.flags.append("suggest_clear")
    return True


def apply_suggestions(ext: ExtractedStatement, verified_only: bool = False) -> ExtractedStatement:
    """Return a copy with suggestions accepted, as a reviewer clicking 'accept' would."""
    out = ext.model_copy(deep=True)
    for t in out.transactions:
        for fv in t.fields.values():
            if verified_only and "suggestion_verified" not in fv.flags:
                continue
            if fv.suggestion is not None:
                fv.value = fv.suggestion
            elif "suggest_clear" in fv.flags:
                fv.value = None
    return out


def score(ext: ExtractedStatement) -> ExtractedStatement:
    """Adjust confidences in place, attach suggestions and fill ``ext.issues``. Returns ``ext``."""
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

    # 2) running-balance chain, bridging unreadable cells with suggestions
    opening_fv = ext.header.get("opening_balance")
    previous: Optional[Decimal] = opening_fv.value if opening_fv else None
    prev_fv: Optional[FieldValue] = opening_fv  # the field that supplied ``previous``
    bad: set[int] = set()
    checked: set[int] = set()
    delta: dict[int, Decimal] = {}
    bridged: dict[int, FieldValue] = {}  # row -> field whose suggestion was used to continue the chain
    prev_bridged: Optional[int] = None

    for i, t in enumerate(txns):
        balance_fv = t.fields.get("balance")
        balance = balance_fv.value if balance_fv else None
        amount = _signed(t)

        if previous is not None and balance is not None and amount is None:
            # unreadable or missing amount: the balances imply it
            _suggest_amount(t, balance - previous, verified=False)
            bridged[i] = t.fields["debit" if balance - previous < 0 else "credit"]
        elif previous is not None and balance is None and amount is not None:
            implied_balance = previous + amount
            if balance_fv is None:
                t.fields["balance"] = balance_fv = FieldValue(text="", value=None, confidence=0.0, source="inferred")
            _suggest(balance_fv, implied_balance, verified=False)
            bridged[i] = balance_fv
            previous, prev_fv, prev_bridged = implied_balance, balance_fv, i
            continue

        if balance is None or amount is None or previous is None:
            previous, prev_fv, prev_bridged = balance, balance_fv, None
            continue

        checked.add(i)
        if previous + amount != balance:
            bad.add(i)
            delta[i] = balance - (previous + amount)
            issues.append({"kind": "balance_mismatch", "row": i, "expected": str(previous + amount),
                           "actual": str(balance)})
        else:
            _verify(_amount_field(t))
            _verify(balance_fv)
            _verify(prev_fv)
            if prev_bridged is not None:  # the bridged suggestion before this row made the chain close
                _suggest(bridged[prev_bridged], bridged[prev_bridged].suggestion, verified=True)
        previous, prev_fv, prev_bridged = balance, balance_fv, None

    # A bridged amount is corroborated when its own balance is verified by the next row.
    for i, fv in bridged.items():
        bal = txns[i].fields.get("balance")
        if fv is not bal and bal is not None and "chain_verified" in bal.flags:
            _suggest(fv, fv.suggestion, verified=True)

    # 3) localize breaks and attach suggestions
    closing = ext.header_value("closing_balance")
    broken = sorted(bad)
    k = 0
    while k < len(broken):
        i = broken[k]
        t = txns[i]
        bal_fv = t.fields.get("balance")
        amount_fields = [t.fields.get("debit"), t.fields.get("credit")]
        stated_prev = t.value("balance") - _signed(t) - delta[i]  # the previous balance used in the check
        if (i + 1) in bad and delta[i] == -delta[i + 1]:
            # balance of row i is off by delta[i]; both checks close once it is corrected
            _lower(bal_fv, 0.20, "balance_chain_break")
            for fv in amount_fields:
                _lower(fv, 0.60, "balance_chain_break")
            _suggest(bal_fv, t.value("balance") - delta[i], verified=True)
            k += 2
            continue
        if i == n - 1:
            amount_implied = t.value("balance") - stated_prev
            if closing is not None and closing == t.value("balance"):
                _suggest_amount(t, amount_implied, verified=True)  # closing agrees with the balance
            elif closing is not None and closing == stated_prev + _signed(t):
                _lower(bal_fv, 0.20, "balance_chain_break")
                _suggest(bal_fv, closing, verified=True)  # closing agrees with the amount
            else:
                _lower(bal_fv, 0.30, "balance_chain_break")
                for fv in amount_fields:
                    _lower(fv, 0.30, "balance_chain_break")
            k += 1
            continue
        # lone break (or the first of two independent errors): the amount is wrong, or a row went missing
        corroborated = (i + 1) not in bad and (i + 1) in checked
        if not _suggest_amount(t, t.value("balance") - stated_prev, verified=corroborated):
            issues.append({"kind": "possible_missing_row", "row": i, "delta": str(delta[i])})
        k += 1

    # 4) closing balance
    if txns and closing is not None and txns[-1].value("balance") is not None:
        if txns[-1].value("balance") != closing:
            issues.append({"kind": "closing_mismatch", "row": None, "expected": str(closing),
                           "actual": str(txns[-1].value("balance"))})
            _lower(ext.header.get("closing_balance"), 0.30, "closing_mismatch")
            if (n - 1) not in bad:
                _lower(txns[-1].fields.get("balance"), 0.30, "closing_mismatch")
        else:
            _verify(ext.header.get("closing_balance"))
            _verify(txns[-1].fields.get("balance"))

    # 5) dates: ordering and period checks. A date that parsed cleanly and sits between its neighbours inside
    # the statement period is corroborated by the document itself; a misread digit usually breaks one of these.
    last_date = None
    start, end = ext.header_value("period_start"), ext.header_value("period_end")
    dates = [t.value("date") for t in txns]
    for i, t in enumerate(txns):
        d = dates[i]
        if d is None:
            continue
        if last_date is not None and d < last_date:
            issues.append({"kind": "date_order", "row": i, "field": "date"})
            _lower(t.fields.get("date"), 0.40, "date_out_of_order")
        if start and end and not (start <= d <= end):
            issues.append({"kind": "out_of_period", "row": i, "field": "date"})
            _lower(t.fields.get("date"), 0.40, "date_outside_period")
        last_date = max(last_date, d) if last_date else d

    for i, t in enumerate(txns):
        fv = t.fields.get("date")
        d = dates[i]
        if fv is None or d is None or fv.flags or fv.confidence < 0.5:
            continue  # untouched, cleanly parsed dates only; repaired or already-flagged ones stay doubtful
        before = next((x for x in reversed(dates[:i]) if x is not None), None)
        after = next((x for x in dates[i + 1:] if x is not None), None)
        in_order = (before is None or before <= d) and (after is None or d <= after)
        in_period = not (start and end) or start <= d <= end
        if in_order and in_period and (before is not None or after is not None):
            fv.confidence = max(fv.confidence, ORDER_VERIFIED_CONF)
            fv.flags.append("date_order_verified")

    # value dates: the same clean-parse test, plus a relationship to the transaction date of the same row
    for t in txns:
        vd, d = t.fields.get("value_date"), t.value("date")
        if vd is None or vd.value is None or d is None or vd.flags or vd.confidence < 0.5:
            continue
        lag = (vd.value - d).days
        if 0 <= lag <= MAX_VALUE_DATE_LAG_DAYS:
            vd.confidence = max(vd.confidence, ORDER_VERIFIED_CONF)
            vd.flags.append("value_date_consistent")
        else:
            _lower(vd, 0.40, "value_date_inconsistent")
            issues.append({"kind": "value_date_inconsistent", "row": txns.index(t), "field": "value_date"})

    ext.issues = issues
    flagged = review_items(ext)
    total_fields = sum(len(t.fields) for t in txns)
    suggestions = [fv for t in txns for fv in t.fields.values() if fv.suggestion is not None]
    ext.meta["summary"] = {
        "rows": n,
        "fields": total_fields,
        "fields_to_review": len(flagged),
        "rows_to_review": len({r for r, _, _, _ in flagged if r is not None}),
        "chain_rows_checked": len(checked),
        "chain_breaks": len(bad),
        "suggestions": len(suggestions),
        "verified_suggestions": sum("suggestion_verified" in fv.flags for fv in suggestions),
        "reconciles": not bad and len(checked) == n and not any(i["kind"] == "closing_mismatch" for i in issues),
    }
    return ext


def review_items(ext: ExtractedStatement, threshold: Optional[float] = None) -> list[tuple[Optional[int], str, float, list[str]]]:
    """(row index or None for header fields, field name, confidence, flags) for everything below its threshold.

    ``threshold`` overrides every field's threshold at once (used by the calibration sweep).
    """
    out = []
    for name, fv in ext.header.items():
        if fv.confidence < (threshold if threshold is not None else threshold_for(name)):
            out.append((None, name, fv.confidence, fv.flags))
    for i, t in enumerate(ext.transactions):
        for name, fv in t.fields.items():
            if fv.confidence < (threshold if threshold is not None else threshold_for(name)):
                out.append((i, name, fv.confidence, fv.flags))
    return out
