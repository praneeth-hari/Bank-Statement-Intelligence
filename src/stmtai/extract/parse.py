"""Parsers for dates and money as they appear on Indian bank statements.

Two modes:

* **strict** (text layer): the text is exactly what the bank printed, so anything unusual is rejected.
* **tolerant** (OCR): recover the value from typical OCR damage - commas read as periods, a lost decimal
  point, ``O`` for ``0``, a merged ``Dr``/``Cr`` suffix, a date with its separators dropped. Every
  tolerant result reports ``repaired=True`` when it had to change anything, so confidence can reflect it.
  Tolerant parsing only guesses; the running-balance chain decides whether the guess was right.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
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

# Finds dates inside a longer line (longest formats first). Spaces around month names are optional so
# OCR text with merged words ('01Jul2026to31Aug2026') is still found.
DATE_FIND_RE = re.compile(
    r"\d{2}[/-]\d{2}[/-]\d{4}|\d{2} ?[A-Za-z]{3} ?\d{4}|\d{2}-[A-Za-z]{3}-\d{4}|\d{2}-[A-Za-z]{3}-\d{2}|\d{2}/\d{2}/\d{2}"
)

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

# Characters OCR commonly returns in place of digits.
_TO_DIGIT = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1", "i": "1",
                           "!": "1", "Z": "2", "z": "2", "S": "5", "s": "5", "B": "8", "G": "6", "T": "7"})
_SEPARATORS = ",.:;'`"


# --------------------------------------------------------------------------- strict
def parse_date(text: str) -> Optional[dt.date]:
    """Parse a full date string (day first, as used in India). Returns None if it is not a date."""
    text = " ".join(text.split())
    m = re.fullmatch(r"(\d{2}) ?([A-Za-z]{3}) ?(\d{4})", text)
    if m:  # tolerate '01Jul2026' as well as '01 Jul 2026'
        text = f"{m.group(1)} {m.group(2)} {m.group(3)}"
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


# --------------------------------------------------------------------------- money with Dr/Cr
@dataclass(frozen=True)
class Money:
    value: Decimal
    suffix: Optional[str] = None  # 'dr' | 'cr' | None
    repaired: bool = False


_STRICT_MONEY = re.compile(r"^(-?\d[\d,]*\.\d{2})(?:\s*(Dr|Cr))?$", re.I)
_TRAILING_SUFFIX = re.compile(r"(?:\s*)(D[rR]?|C[rR]?|d[r]?|c[r]?)\.?$")


def parse_money(text: str, tolerant: bool = False) -> Optional[Money]:
    """Parse an amount with an optional Dr/Cr suffix, strictly or tolerantly."""
    text = " ".join(text.split())
    if not text:
        return None
    m = _STRICT_MONEY.match(text)
    if m:
        try:
            value = Decimal(m.group(1).replace(",", ""))
        except InvalidOperation:
            return None
        suffix = m.group(2).lower() if m.group(2) else None
        return Money(value, suffix, repaired=False)
    if not tolerant:
        return None
    return _tolerant_money(text)


def _tolerant_money(text: str) -> Optional[Money]:
    body, suffix = text, None
    sm = _TRAILING_SUFFIX.search(body)
    # Only treat trailing letters as a suffix when digits come before them.
    if sm and re.search(r"\d", body[: sm.start()]):
        suffix = "dr" if sm.group(1)[0] in "Dd" else "cr"
        body = body[: sm.start()]

    negative = body.strip().startswith("-")
    compact = body.replace(" ", "").lstrip("-")
    digits_only = sum(ch.isdigit() for ch in compact)
    if digits_only == 0 or digits_only < 0.6 * max(len(compact), 1):
        return None  # mostly letters: this is not an amount

    mapped = compact.translate(_TO_DIGIT)
    cleaned = "".join(ch for ch in mapped if ch.isdigit() or ch in _SEPARATORS)
    digits = "".join(ch for ch in cleaned if ch.isdigit())
    if len(digits) < 3:
        return None

    # The decimal point is the last separator if exactly two digits follow it; otherwise the decimal point
    # was lost and every amount on a statement has paise, so the last two digits are the paise.
    last_sep = max(cleaned.rfind(s) for s in _SEPARATORS)
    if last_sep >= 0 and len(cleaned) - last_sep - 1 == 2 and cleaned[:last_sep].strip(_SEPARATORS):
        whole = "".join(ch for ch in cleaned[:last_sep] if ch.isdigit())
        frac = cleaned[last_sep + 1:]
    else:
        whole, frac = digits[:-2], digits[-2:]
    if not whole:
        whole = "0"
    try:
        value = Decimal(f"{int(whole)}.{frac}")
    except (InvalidOperation, ValueError):
        return None
    if negative:
        value = -value
    return Money(value, suffix, repaired=True)


# --------------------------------------------------------------------------- tolerant dates
@dataclass(frozen=True)
class ParsedDate:
    value: dt.date
    repaired: bool = False


def _month_from_letters(letters: str) -> Optional[int]:
    word = letters.upper().replace("0", "O")
    if word[:3] in MONTHS:
        return MONTHS.index(word[:3]) + 1
    candidates = [i for i, m in enumerate(MONTHS) if m.startswith(word[:2])] if len(word) >= 2 else []
    if len(candidates) == 1:  # 'NO' -> NOV is unique; 'JU' (JUN/JUL) is not
        return candidates[0] + 1
    return None


def _year(text: str) -> Optional[int]:
    if len(text) == 4:
        return int(text)
    if len(text) == 2:
        return 2000 + int(text)
    return None


def parse_date_tolerant(text: str) -> Optional[ParsedDate]:
    """Parse a date from OCR text; ``repaired`` is True when the text was not a clean date."""
    strict = parse_date(text)
    if strict is not None:
        return ParsedDate(strict, repaired=False)

    s = "".join(text.split())
    # Month-name dates: '08Nov25', '0BNoV25', '11-NOV25', '12No-25'
    m = re.fullmatch(r"([0-9OoIlBSDZ]{1,2})[-/.:]?([A-Za-z0]{2,4})[-/.:]?([0-9OoIlBSDZ]{2,4})", s)
    if m:
        letters = m.group(2)
        if re.search(r"[A-Za-z]", letters):
            month = _month_from_letters(letters)
            day_txt = m.group(1).translate(_TO_DIGIT)
            year = _year(m.group(3).translate(_TO_DIGIT))
            if month and day_txt.isdigit() and year:
                try:
                    return ParsedDate(dt.date(year, month, int(day_txt)), repaired=True)
                except ValueError:
                    return None

    # Numeric dates with damaged or missing separators: '03042025', '03:04:2025', '0304/2025'
    digits = "".join(ch for ch in s.translate(_TO_DIGIT) if ch.isdigit())
    for day_len, month_len, year_len in ((2, 2, 4), (2, 2, 2)):
        if len(digits) == day_len + month_len + year_len:
            day = int(digits[:2])
            month = int(digits[2:4])
            year = _year(digits[4:])
            try:
                return ParsedDate(dt.date(year, month, day), repaired=True) if year else None
            except ValueError:
                return None
    return None


def looks_like_date(text: str) -> bool:
    """A date column cell that is damaged beyond parsing but still clearly a date (enough digits)."""
    s = "".join(text.split())
    if not s or len(s) > 14:
        return False
    if parse_date_tolerant(s):
        return True
    return sum(ch.isdigit() for ch in s.translate(_TO_DIGIT)) >= 4
