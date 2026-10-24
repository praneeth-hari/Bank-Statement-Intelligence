"""Run a ``Query`` over rows. Plain Python, no eval, no SQL: whatever produced the Query cannot reach anything else."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from .data import Row, primary_category
from .model import Query

TWO = Decimal("0.01")


@dataclass
class Answer:
    kind: str                                   # number | groups | rows | none
    value: Optional[Decimal] = None             # a total, an average, a count or a single amount
    groups: list[tuple[str, Decimal]] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)   # the rows the answer was computed from (capped), best first
    matched: int = 0                            # how many transactions matched the filters
    unit: str = "INR"                           # INR or transactions


def _amount(row: Row, measure: str) -> Decimal:
    if measure == "net":
        return row.signed
    if measure == "balance":
        return row.balance
    return row.amount


def matching(q: Query, rows: list[Row]) -> list[Row]:
    out = []
    for r in rows:
        if q.date_from and r.date < q.date_from:
            continue
        if q.date_to and r.date > q.date_to:
            continue
        if q.measure == "debit" and r.debit is None:
            continue
        if q.measure == "credit" and r.credit is None:
            continue
        if q.categories and not set(q.categories) & set(r.tags):
            continue
        text = r.description.casefold()
        if q.text and not all(t in text for t in q.text):
            continue
        amount = abs(r.signed)
        if q.min_amount is not None and amount < q.min_amount:
            continue
        if q.max_amount is not None and amount > q.max_amount:
            continue
        out.append(r)
    return out


def _group_key(q: Query, r: Row) -> str:
    if q.group_by == "month":
        return f"{r.date:%Y-%m}"
    if q.group_by == "category":
        return primary_category(r.tags)
    return r.payee or "(no payee)"


def _reduce(aggregate: str, measure: str, rs: list[Row]) -> Optional[Decimal]:
    if aggregate == "count":
        return Decimal(len(rs))
    if not rs:
        return None
    vals = [_amount(r, measure) for r in rs]
    if aggregate == "sum":
        return sum(vals, Decimal("0")).quantize(TWO)
    if aggregate == "avg":
        return (sum(vals, Decimal("0")) / len(vals)).quantize(TWO)
    if aggregate == "max":
        return max(vals)
    if aggregate == "min":
        return min(vals)
    raise ValueError(aggregate)


def run(q: Query, rows: list[Row], show: int = 20) -> Answer:
    hit = matching(q, rows)
    unit = "transactions" if q.aggregate == "count" else "INR"

    if q.group_by:
        buckets: dict[str, list[Row]] = {}
        for r in hit:
            buckets.setdefault(_group_key(q, r), []).append(r)
        groups = [(k, _reduce(q.aggregate, q.measure, rs)) for k, rs in buckets.items()]
        groups = [(k, v) for k, v in groups if v is not None]
        if q.group_by == "month":
            groups.sort(key=lambda g: g[0])
        else:
            groups.sort(key=lambda g: (g[1], g[0]), reverse=(q.order == "desc"))
        return Answer("groups", groups=groups[:q.limit], rows=hit[:show], matched=len(hit), unit=unit)

    if q.aggregate == "list":
        ranked = sorted(hit, key=lambda r: (abs(r.signed), r.date, r.row), reverse=(q.order == "desc"))
        return Answer("rows", rows=ranked[:q.limit], matched=len(hit), unit=unit)

    if q.aggregate == "last":
        if not hit:
            return Answer("none", matched=0)
        final = max(hit, key=lambda r: (r.date, r.statement_id, r.row))
        return Answer("number", value=final.balance, rows=[final], matched=len(hit))

    value = _reduce(q.aggregate, q.measure, hit)
    if value is None:
        return Answer("none", matched=0, unit=unit)
    shown = hit
    if q.aggregate in ("max", "min"):
        pick = max if q.aggregate == "max" else min
        shown = [pick(hit, key=lambda r: _amount(r, q.measure))]
    return Answer("number", value=value, rows=shown[:show], matched=len(hit), unit=unit)
