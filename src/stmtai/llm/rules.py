"""Deterministic text and date proposals, tried before any model is asked.

The first real-model run (qwen2.5:3b on 12 medium scans) showed where the errors are: OCR reads the letter O as
the digit 0 (``P00JAPUROHIT``, ``B00KMYSHOW``), a space as ``.`` (``RELIANCE.SMART``), and a month name loses a
letter (``29-Ju-26``). A rule fixes each of these exactly and for free, which a 3B model did not. So the model
only sees what the rules cannot settle.

Rules propose, they do not overwrite: the output goes through the same checks as a model answer and reaches the
reviewer as a suggestion flagged ``rule_suggested``. They only touch the *name* part of a payment description,
never the reference digits, and only digits sitting between letters inside a word, so a handle that ends in
digits (``rahul123``) is left alone.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Optional

from ..extract.scoring import edit_distance

_RAIL = re.compile(r"^(UPI|IMPS)/(\d{10,13})(/?)(.*)$", re.S)
_LOOKALIKE = {"0": "O", "1": "I", "5": "S", "8": "B"}
_INSIDE_WORD = re.compile(r"(?<=[A-Za-z])([0158]+)(?=[A-Za-z])")
_BETWEEN_LETTERS = re.compile(r"(?<=[A-Za-z])[.:·_](?=[A-Za-z])")


def description_rule(read: str) -> Optional[str]:
    """A repaired description, or None when no rule applies."""
    m = _RAIL.match(read.strip())
    if not m:
        return None
    rail, ref, slash, name = m.groups()
    fixed = _INSIDE_WORD.sub(lambda g: "".join(_LOOKALIKE[c] for c in g.group(1)), name)
    fixed = _BETWEEN_LETTERS.sub(" ", fixed)
    if not slash and name[:1].isalpha():
        slash = "/"  # the separator between the reference and the name was lost
    out = f"{rail}/{ref}{slash}{fixed}"
    return out if out != read.strip() else None


_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_DATE_HEAD = re.compile(r"^\W*(\d{1,2})\s*[-/. ~]?\s*([A-Za-z]{2,4})\s*[-/. ~]?\s*(\d{2}|\d{4})(?!\d)")


def date_head(text: str) -> Optional[str]:
    """The ``dd-Mon-yy`` part of a date cell, which can also have swallowed the start of the next column."""
    m = _DATE_HEAD.match(text)
    return m.group(0).strip() if m else None


def date_rule(text: str, before: Optional[dt.date], after: Optional[dt.date], start: Optional[dt.date],
              end: Optional[dt.date]) -> Optional[str]:
    """ISO date for a ``dd-Mon-yy`` style date whose month name lost or changed a letter, resolved by the
    neighbouring dates. None unless exactly one month fits."""
    m = _DATE_HEAD.match(text)
    if not m:
        return None
    day, letters, year = int(m.group(1)), m.group(2).casefold(), int(m.group(3))
    year += 2000 if year < 100 else 0
    fits = []
    for i, abbr in enumerate(_MONTHS, 1):
        if not (abbr.startswith(letters) or edit_distance(letters, abbr) <= 1):
            continue
        try:
            d = dt.date(year, i, day)
        except ValueError:
            continue
        if before is not None and d < before or after is not None and d > after:
            continue
        if start is not None and end is not None and not (start <= d <= end):
            continue
        fits.append(d)
    return fits[0].isoformat() if len(fits) == 1 else None
