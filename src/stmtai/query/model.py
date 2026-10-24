"""The structured form of a question. This is the only thing a parser (rules or model) may produce."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

Aggregate = Literal["sum", "count", "max", "min", "avg", "list", "last"]
Measure = Literal["debit", "credit", "net", "balance"]
Category = Literal["upi", "imps", "neft", "pos", "atm", "emi", "salary", "charges", "interest"]
GroupBy = Literal["month", "category", "payee"]
CATEGORIES: tuple[str, ...] = ("upi", "imps", "neft", "pos", "atm", "emi", "salary", "charges", "interest")

MAX_LIMIT = 50


class Query(BaseModel):
    aggregate: Aggregate
    measure: Measure = "debit"            # debit/credit pick only those rows; net and balance use every row
    date_from: Optional[dt.date] = None
    date_to: Optional[dt.date] = None     # inclusive
    categories: list[Category] = Field(default_factory=list)   # any of these
    text: list[str] = Field(default_factory=list)              # all of these must appear in the description
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    group_by: Optional[GroupBy] = None
    limit: int = 10                       # for list and for grouped answers
    order: Literal["desc", "asc"] = "desc"

    @field_validator("text")
    @classmethod
    def _clean_text(cls, v: list[str]) -> list[str]:
        out = [t.strip().casefold() for t in v if t and t.strip()]
        if any(len(t) > 40 for t in out) or len(out) > 4:
            raise ValueError("too many or too long search terms")
        return out

    @field_validator("limit")
    @classmethod
    def _bound_limit(cls, v: int) -> int:
        return max(1, min(v, MAX_LIMIT))

    @model_validator(mode="after")
    def _consistent(self) -> "Query":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from is after date_to")
        if self.aggregate == "last" and self.measure != "balance":
            raise ValueError("'last' only makes sense for the balance")
        if self.group_by and self.aggregate in ("list", "last"):
            raise ValueError("cannot group a list")
        return self


def describe(q: Query) -> str:
    """The question as the system understood it, in plain words, so the user can see a misreading."""
    what = {"sum": "total", "count": "number of", "max": "largest", "min": "smallest", "avg": "average",
            "list": f"the {q.limit} {'largest' if q.order == 'desc' else 'smallest'}", "last": "last balance"}[q.aggregate]
    kind = {"debit": "debits", "credit": "credits", "net": "net change (credits minus debits)", "balance": "balance"}[q.measure]
    if q.measure == "net" and q.aggregate in ("count", "list"):
        kind = "transactions"
    parts = [f"{what} {kind}" if q.aggregate != "last" else what]
    if q.categories:
        parts.append("of type " + " or ".join(c.upper() for c in q.categories))
    if q.text:
        parts.append("mentioning " + " and ".join(f"'{t}'" for t in q.text))
    if q.date_from or q.date_to:
        parts.append(f"from {q.date_from or 'the start'} to {q.date_to or 'the end'}")
    if q.min_amount is not None:
        parts.append(f"at least {q.min_amount}")
    if q.max_amount is not None:
        parts.append(f"at most {q.max_amount}")
    if q.group_by:
        parts.append(f"grouped by {q.group_by}")
    return ", ".join(parts)
