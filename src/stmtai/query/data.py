"""Rows to query: one per transaction, with a type and a payee worked out from the description."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

from ..extract.models import ExtractedStatement
from ..llm.vocab import name_of

# order matters for the single "primary" category used when grouping
PRIMARY_ORDER = ("salary", "emi", "charges", "interest", "upi", "imps", "neft", "pos", "atm")
_CHARGES = re.compile(r"SMS ALERT|DEBIT CARD AMC|GST ON|CHARGES", re.I)


def tags_of(description: str) -> tuple[str, ...]:
    d = description.upper().strip()
    tags = []
    if d.startswith("UPI/"):
        tags.append("upi")
    if d.startswith("IMPS/"):
        tags.append("imps")
    if d.startswith("NEFT"):
        tags.append("neft")
    if d.startswith("POS "):
        tags.append("pos")
    if d.startswith("ATM"):
        tags.append("atm")
    if "EMI" in d.split("/")[0] or d.startswith("ECS"):
        tags.append("emi")
    if "SALARY" in d:
        tags.append("salary")
    if _CHARGES.search(d):
        tags.append("charges")
    if "INTEREST" in d:
        tags.append("interest")
    return tuple(tags)


def primary_category(tags: Iterable[str]) -> str:
    tags = set(tags)
    return next((c for c in PRIMARY_ORDER if c in tags), "other")


@dataclass(frozen=True)
class Row:
    statement_id: str
    filename: str
    row: int
    date: dt.date
    description: str
    ref: Optional[str]
    debit: Optional[Decimal]
    credit: Optional[Decimal]
    balance: Decimal
    tags: tuple[str, ...]
    payee: Optional[str]

    @property
    def amount(self) -> Decimal:
        return self.credit if self.credit is not None else self.debit  # type: ignore[return-value]

    @property
    def signed(self) -> Decimal:
        return self.credit if self.credit is not None else -self.debit  # type: ignore[operator]


def make_row(statement_id: str, filename: str, row: int, date: dt.date, description: str, ref: Optional[str],
             debit: Optional[Decimal], credit: Optional[Decimal], balance: Decimal) -> Row:
    name = name_of(description)
    return Row(statement_id, filename, row, date, description, ref, debit, credit, balance,
               tags_of(description), name.casefold() if name else None)


def rows_from_extraction(ext: ExtractedStatement, statement_id: str, filename: str) -> list[Row]:
    """Rows from a reviewed extraction. A row is skipped, not guessed at, if it lacks a date, a balance or exactly one amount."""
    rows = []
    for i, t in enumerate(ext.transactions):
        date, balance, debit, credit = t.value("date"), t.value("balance"), t.value("debit"), t.value("credit")
        if date is None or balance is None or (debit is None) == (credit is None):
            continue
        rows.append(make_row(statement_id, filename, i, date, str(t.value("description") or ""), t.value("ref"),
                             debit, credit, balance))
    return rows
