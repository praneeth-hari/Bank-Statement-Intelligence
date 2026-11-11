"""Filter, sort and page the transactions of approved statements.

Pure functions over ``Row`` objects, so every result can be checked against a plain loop. Totals of what matched are
exact decimals, and debits and credits are reported side by side, never netted (the statements may be different accounts).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from ..query.data import Row, primary_category
from .categories import UNCATEGORISED, Rule, category_of

TWO = Decimal("0.01")
MAX_LIMIT = 500


@dataclass
class Filters:
    q: Optional[str] = None
    date_from: Optional[dt.date] = None
    date_to: Optional[dt.date] = None
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    type: Optional[str] = None
    direction: str = "any"                 # any | debit | credit
    statement_id: Optional[str] = None
    category: Optional[str] = None         # a name, or "Uncategorised"
    sort: str = "date"                     # date | amount
    order: str = "desc"


def _s(x: Decimal) -> str:
    return f"{x.quantize(TWO):.2f}"


def matches(r: Row, cat: str, f: Filters) -> bool:
    needle = (f.q or "").strip().casefold()
    if needle and needle not in r.description.casefold():          # a box with only spaces in it is no search
        return False
    if f.date_from and r.date < f.date_from:
        return False
    if f.date_to and r.date > f.date_to:
        return False
    if f.min_amount is not None and r.amount < f.min_amount:
        return False
    if f.max_amount is not None and r.amount > f.max_amount:
        return False
    if f.type and primary_category(r.tags) != f.type:
        return False
    if f.direction == "debit" and r.debit is None:
        return False
    if f.direction == "credit" and r.credit is None:
        return False
    if f.statement_id and r.statement_id != f.statement_id:
        return False
    if f.category and cat.casefold() != f.category.casefold():
        return False
    return True


def run(rows: list[Row], rules: list[Rule], f: Filters, limit: int, offset: int) -> dict[str, Any]:
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)
    tagged = [(r, category_of(r.description, rules)) for r in rows]
    hit = [(r, c) for r, c in tagged if matches(r, c, f)]
    hit.sort(key=lambda rc: (rc[0].filename, rc[0].statement_id, rc[0].row))           # a stable base order...
    key = (lambda rc: rc[0].date) if f.sort == "date" else (lambda rc: rc[0].amount)
    hit.sort(key=key, reverse=(f.order == "desc"))                                     # ...so equal keys keep it

    debits = [r.debit for r, _ in hit if r.debit is not None]
    credits = [r.credit for r, _ in hit if r.credit is not None]
    page = hit[offset: offset + limit]
    seen_statements = {r.statement_id: r.filename for r in rows}
    return {
        "has_data": bool(rows),
        "matched": len(hit),
        "totals": {"debit": _s(sum(debits, Decimal(0))), "credit": _s(sum(credits, Decimal(0))),
                   "debits": len(debits), "credits": len(credits)},
        "limit": limit, "offset": offset,
        "rows": [{"statement_id": r.statement_id, "filename": r.filename, "row": r.row, "date": r.date.isoformat(),
                  "description": r.description, "ref": r.ref,
                  "debit": None if r.debit is None else _s(r.debit), "credit": None if r.credit is None else _s(r.credit),
                  "balance": _s(r.balance), "type": primary_category(r.tags), "category": c} for r, c in page],
        "facets": {
            "statements": [{"id": k, "filename": v} for k, v in seen_statements.items()],
            "types": sorted({primary_category(r.tags) for r in rows}),
            "categories": sorted({c for _, c in tagged} - {UNCATEGORISED}) + ([UNCATEGORISED] if any(c == UNCATEGORISED for _, c in tagged) else []),
        },
        "notes": (["These combine several statements, which may belong to different accounts, so money in and money out are not netted."]
                  if len(seen_statements) > 1 else []),
    }
