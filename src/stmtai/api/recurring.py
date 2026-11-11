"""Payments that come round again, found in approved statements.

A payment counts as repeating when the same payee, in the same direction, shows up in at least three different
calendar months, and no more than twice in any one month (so everyday spending at one shop is not called a
subscription). The payee is the description with its numbers taken out, so ``UPI/973530608279/AIRTEL PAYMENTS``
and ``UPI/411100224410/AIRTEL PAYMENTS`` are the same payee, and ``ECS/EMI HOME LOAN LN21819600`` and
``ECS/EMI HOME LOAN LN47642772`` are too.

It only looks at months that have an approved statement. A month with no statement is unknown, not missed, so a
payment can repeat across a gap. With fewer than three months of data it says there is not enough to tell.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any

from ..query.data import Row

MIN_MONTHS = 3
MAX_PER_MONTH = 2
CLOSE = Decimal("0.02")                    # amounts within 2% of each other count as "about the same"
TWO = Decimal("0.01")
_SPLIT = re.compile(r"[/\-]")
RAILS = {"UPI", "IMPS", "NEFT", "ECS", "POS", "ATM", "RTGS", "NACH"}


def clean_description(description: str) -> str:
    """The description with every word that holds a digit removed (references, loan and phone numbers)."""
    words = [w for part in _SPLIT.split(description.upper()) for w in part.split() if not any(ch.isdigit() for ch in w)]
    return " ".join(words)


def _s(x: Decimal) -> str:
    return f"{x.quantize(TWO):.2f}"


def find_recurring(rows: list[Row]) -> dict[str, Any]:
    months_all = {(r.date.year, r.date.month) for r in rows}
    out: dict[str, Any] = {"has_data": bool(rows), "months_covered": len(months_all), "items": [],
                           "rules": f"At least {MIN_MONTHS} different months, and no more than {MAX_PER_MONTH} payments in any one month.",
                           "note": "Only months with an approved statement are looked at, so a payment can still repeat across months that are missing here."}
    if len(months_all) < MIN_MONTHS:
        out["reason"] = (f"Approved statements cover {len(months_all)} month{'' if len(months_all) == 1 else 's'}. "
                         f"At least {MIN_MONTHS} are needed to tell what repeats.")
        return out

    groups: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for r in rows:
        key = clean_description(r.description)
        if key:
            groups[("debit" if r.debit is not None else "credit", key)].append(r)

    items = []
    for (direction, key), g in groups.items():
        per_month = Counter((r.date.year, r.date.month) for r in g)
        if len(per_month) < MIN_MONTHS or max(per_month.values()) > MAX_PER_MONTH:
            continue
        amounts = [r.amount for r in g]
        low, high = min(amounts), max(amounts)
        kind = "same" if low == high else "close" if (high - low) <= low * CLOSE else "varies"
        words = key.split()
        rail = words[0] if words[0] in RAILS else None
        label = " ".join(words[1:]) if rail and len(words) > 1 else key
        dates = sorted(r.date for r in g)
        items.append({
            "label": label, "rail": rail, "direction": direction, "count": len(g), "months": len(per_month),
            "amount_kind": kind, "low": _s(low), "high": _s(high), "total": _s(sum(amounts, Decimal(0))),
            "day_of_month": statistics.median_low([d.day for d in dates]),
            "first_date": dates[0].isoformat(), "last_date": dates[-1].isoformat(),
            "dates": [d.isoformat() for d in dates],
        })
    items.sort(key=lambda i: (-i["months"], -Decimal(i["total"]), i["label"]))
    out["items"] = items
    return out
