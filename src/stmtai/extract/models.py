"""Extraction output: every value carries its text, a confidence and where it came from on the page."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..schema import Statement, Transaction, money


class BBox(BaseModel):
    page: int
    x0: float
    y0: float
    x1: float
    y1: float


class FieldValue(BaseModel):
    text: str  # raw text as read from the document
    value: Any = None  # parsed value (date, Decimal or str); None when parsing failed
    confidence: float = 0.0
    bbox: Optional[BBox] = None
    source: str = "text_layer"  # text_layer | ocr | inferred
    flags: list[str] = Field(default_factory=list)  # why confidence was lowered, e.g. 'balance_chain_break'


class ExtractedTransaction(BaseModel):
    fields: dict[str, FieldValue] = Field(default_factory=dict)

    def value(self, name: str) -> Any:
        fv = self.fields.get(name)
        return fv.value if fv else None


class ExtractedStatement(BaseModel):
    source_file: str = ""
    pages: int = 0
    header: dict[str, FieldValue] = Field(default_factory=dict)
    transactions: list[ExtractedTransaction] = Field(default_factory=list)
    issues: list[dict] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    def header_value(self, name: str) -> Any:
        fv = self.header.get(name)
        return fv.value if fv else None


def to_statement(ext: ExtractedStatement) -> Statement:
    """Convert to the plain ``Statement`` used for reconciliation and evaluation.

    Rows that cannot form a valid transaction (no date, no balance, or no usable amount) are dropped here
    and reported as issues by the scoring step, never silently repaired.
    """
    txns: list[Transaction] = []
    for t in ext.transactions:
        date, balance = t.value("date"), t.value("balance")
        debit, credit = t.value("debit"), t.value("credit")
        if date is None or balance is None or (debit is None) == (credit is None):
            continue
        txns.append(
            Transaction(
                date=date,
                value_date=t.value("value_date"),
                description=t.value("description") or "",
                ref=t.value("ref"),
                debit=debit,
                credit=credit,
                balance=balance,
            )
        )

    def h(name: str, default: Any = "") -> Any:
        v = ext.header_value(name)
        return default if v is None else v

    opening = ext.header_value("opening_balance")
    if opening is None and txns:
        opening = money(txns[0].balance - txns[0].signed_amount)
    closing = ext.header_value("closing_balance")
    if closing is None and txns:
        closing = txns[-1].balance
    first = txns[0].date if txns else dt.date(1970, 1, 1)
    last = txns[-1].date if txns else first

    return Statement(
        bank_name=h("bank_name"),
        account_holder=h("account_holder"),
        account_number=h("account_number"),
        ifsc=h("ifsc"),
        branch=h("branch"),
        currency=h("currency", "INR"),
        period_start=h("period_start", first),
        period_end=h("period_end", last),
        opening_balance=opening if opening is not None else Decimal("0.00"),
        closing_balance=closing if closing is not None else Decimal("0.00"),
        transactions=txns,
    )
