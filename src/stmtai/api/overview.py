"""Numbers for the dashboard, computed from approved statements only.

A pure function over rows already parsed by ``stmtai.query.data``, so every figure on the dashboard can be
checked with a plain loop. Money stays ``Decimal`` until the last step and leaves as a two-decimal string,
so nothing goes through floating point on the way to the screen.

Two honest limits are carried in the result rather than hidden by it:

* totals add up statements that may belong to different accounts, and say so (the UI shows the note);
* a balance belongs to one account, so balances are listed per statement and never summed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from ..query.data import Row, primary_category
from .categories import Rule, category_of

TWO = Decimal("0.01")
LARGEST = 6


def _s(x: Decimal) -> str:
    return f"{x.quantize(TWO):.2f}"


@dataclass
class Source:
    """One approved statement: who it is, and the rows that can be counted."""

    statement_id: str
    filename: str
    bank: Optional[str]
    period_start: Optional[str]
    period_end: Optional[str]
    rows: list[Row] = field(default_factory=list)


def build_overview(sources: list[Source], counts: dict[str, int], rules: Optional[list[Rule]] = None) -> dict[str, Any]:
    """``counts``: statements by state (total, approved, awaiting, processing, failed) and fields still to review."""
    rows = [r for s in sources for r in s.rows]
    debits = [r for r in rows if r.debit is not None]
    credits = [r for r in rows if r.credit is not None]

    by_month: dict[str, Decimal] = defaultdict(Decimal)
    for r in debits:
        by_month[f"{r.date.year:04d}-{r.date.month:02d}"] += r.debit  # type: ignore[operator]

    by_type: dict[str, list] = defaultdict(lambda: [Decimal(0), 0])
    for r in debits:
        cell = by_type[primary_category(r.tags)]
        cell[0] += r.debit  # type: ignore[operator]
        cell[1] += 1

    by_cat: dict[str, list] = defaultdict(lambda: [Decimal(0), 0])
    if rules:                                      # with no rules there is nothing to show: not one big "Uncategorised"
        for r in debits:
            cell = by_cat[category_of(r.description, rules)]
            cell[0] += r.debit  # type: ignore[operator]
            cell[1] += 1

    balances = []
    for s in sources:
        if not s.rows:
            continue
        ordered = sorted(s.rows, key=lambda r: r.row)  # document order, not date order: a balance is the one printed on that line
        first, last = ordered[0], ordered[-1]
        dates = [r.date for r in s.rows]
        balances.append({
            "statement_id": s.statement_id, "filename": s.filename, "bank": s.bank,
            "period_start": s.period_start or min(dates).isoformat(), "period_end": s.period_end or max(dates).isoformat(),
            "first_date": first.date.isoformat(), "last_date": last.date.isoformat(),
            "first_balance": _s(first.balance), "last_balance": _s(last.balance), "rows": len(s.rows),
        })

    largest = sorted(debits, key=lambda r: (-r.debit, r.date, r.filename, r.row))[:LARGEST]  # type: ignore[operator]

    notes = []
    if len(sources) > 1:
        notes.append("The totals combine several statements, which may belong to different accounts, so money in and money out are not netted.")
    return {
        "has_data": bool(rows),
        "statements": counts,
        "totals": {"debit": _s(sum((r.debit for r in debits), Decimal(0))),  # type: ignore[misc]
                   "credit": _s(sum((r.credit for r in credits), Decimal(0))),  # type: ignore[misc]
                   "transactions": len(rows), "debits": len(debits), "credits": len(credits)},
        "by_month": [{"month": m, "debit": _s(v)} for m, v in sorted(by_month.items())],
        "by_type": [{"type": t, "debit": _s(v[0]), "count": v[1]}
                    for t, v in sorted(by_type.items(), key=lambda kv: (-kv[1][0], kv[0]))],
        "by_category": [{"category": c, "debit": _s(v[0]), "count": v[1]}
                        for c, v in sorted(by_cat.items(), key=lambda kv: (-kv[1][0], kv[0]))],
        "balances": balances,
        "largest_debits": [{"statement_id": r.statement_id, "filename": r.filename, "row": r.row, "date": r.date.isoformat(),
                            "description": r.description, "debit": _s(r.debit)} for r in largest],  # type: ignore[arg-type]
        "notes": notes,
    }
