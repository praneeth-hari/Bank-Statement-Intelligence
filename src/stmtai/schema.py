"""Pydantic schema shared by the generator, the extractor and the review API.

Money is always ``Decimal`` quantized to two places. Dates are ``datetime.date``.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, model_validator

TWO_PLACES = Decimal("0.01")


def money(value) -> Decimal:
    """Convert a number or string to a Decimal with two decimal places."""
    return Decimal(str(value)).quantize(TWO_PLACES)


class Transaction(BaseModel):
    date: dt.date
    value_date: Optional[dt.date] = None
    description: str
    ref: Optional[str] = None
    debit: Optional[Decimal] = None
    credit: Optional[Decimal] = None
    balance: Decimal

    @model_validator(mode="after")
    def _exactly_one_amount(self) -> "Transaction":
        has_debit = self.debit is not None
        has_credit = self.credit is not None
        if has_debit == has_credit:
            raise ValueError("a transaction must have exactly one of debit or credit")
        return self

    @property
    def signed_amount(self) -> Decimal:
        return self.credit if self.credit is not None else -self.debit  # type: ignore[operator]


class Statement(BaseModel):
    bank_name: str
    account_holder: str
    account_number: str
    ifsc: str
    branch: str
    currency: str = "INR"
    period_start: dt.date
    period_end: dt.date
    opening_balance: Decimal
    closing_balance: Decimal
    transactions: list[Transaction] = Field(default_factory=list)


class Label(BaseModel):
    """Ground truth for one synthetic document."""

    doc_id: str
    layout: str
    seed: int
    fields_present: list[str]
    statement: Statement
