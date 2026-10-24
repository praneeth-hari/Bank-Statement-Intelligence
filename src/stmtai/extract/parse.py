"""Small, strict parsers for dates and money as they appear on Indian bank statements."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

AMOUNT_RE = re.compile(r"^-?\d[\d,]*\.\d{2}$")

_DATE_FORMATS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^\d{2}/\d{2}/\d{4}$"), "%d/%m/%Y"),
    (re.compile(r"^\d{2}-\d{2}-\d{4}$"), "%d-%m-%Y"),
    (re.compile(r"^\d{2} [A-Za-z]{3} \d{4}$"), "%d %b %Y"),
    (re.compile(r"^\d{2}-[A-Za-z]{3}-\d{4}$"), "%d-%b-%Y"),
    (re.compile(r"^\d{2}-[A-Za-z]{3}-\d{2}$"), "%d-%b-%y"),
    (re.compile(r"^\d{2}/\d{2}/\d{2}$"), "%d/%m/%y"),
]

# Finds dates inside a longer line (longest formats first).
DATE_FIND_RE = re.compile(
    r"\d{2}[/-]\d{2}[/-]\d{4}|\d{2} [A-Za-z]{3} \d{4}|\d{2}-[A-Za-z]{3}-\d{4}|\d{2}-[A-Za-z]{3}-\d{2}|\d{2}/\d{2}/\d{2}"
)


def parse_date(text: str) -> Optional[dt.date]:
    """Parse a full date string (day first, as used in India). Returns None if it is not a date."""
    text = " ".join(text.split())
    for pattern, fmt in _DATE_FORMATS:
        if pattern.match(text):
            try:
                return dt.datetime.strptime(text, fmt).date()
            except ValueError:
                return None
    return None


def parse_amount(text: str) -> Optional[Decimal]:
    """Parse '1,23,456.78' or '1,234.56' into a Decimal. Requires exactly two decimals."""
    text = text.strip()
    if not AMOUNT_RE.match(text):
        return None
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def is_amount(text: str) -> bool:
    return bool(AMOUNT_RE.match(text.strip()))
