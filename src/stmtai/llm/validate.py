"""Checks a proposed value has to pass before a reviewer ever sees it.

The model is a proposer, not an authority. Each check below is something the document itself can confirm
without trusting the model: the digits in the text, the neighbouring dates, the statement period. A proposal
that fails any of them is dropped (and counted, so the report shows how often the model oversteps).

Every function returns ``None`` when the proposal is acceptable, otherwise a short machine-readable reason.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Optional

from ..extract.scoring import edit_distance

MAX_TEXT_EDITS = 3  # letters, case and spaces aside; OCR slips are one or two characters
MAX_TEXT_EDIT_RATIO = 0.25
MAX_DESCRIPTION_CHARS = 120
RAIL_PREFIXES = ("UPI/", "IMPS/")


def squash(text: str) -> str:
    """Case- and whitespace-insensitive form, the same notion of 'equal' the evaluation uses."""
    return "".join(text.split()).casefold()


def digit_string(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def long_digit_runs(text: str) -> list[str]:
    return re.findall(r"\d{10,}", text)


def check_description(read: str, proposed: Optional[str], lookalikes: bool = False) -> Optional[str]:
    """``lookalikes=True`` is for the rules, which may turn a 0 inside a word back into the letter O: only the
    reference number (a run of 10+ digits) must then be unchanged, instead of every digit."""
    if proposed is None or not proposed.strip():
        return "empty"
    if "\n" in proposed or len(proposed) > MAX_DESCRIPTION_CHARS:
        return "malformed"
    if not proposed.isprintable():
        return "malformed"
    a, b = squash(read), squash(proposed)
    if a == b:
        return "no_change"  # same text; at most spacing or case differs, which a reviewer cannot act on
    if (long_digit_runs(read) != long_digit_runs(proposed)) if lookalikes else (digit_string(read) != digit_string(proposed)):
        return "changed_digits"  # amounts of money and reference numbers are never the model's to change
    for prefix in RAIL_PREFIXES:
        if read.upper().startswith(prefix) and not proposed.upper().startswith(prefix):
            return "lost_prefix"
    edits = edit_distance(a, b)
    if edits > MAX_TEXT_EDITS or edits > MAX_TEXT_EDIT_RATIO * max(len(a), 1):
        return "too_many_edits"
    return None


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def check_date(text: str, proposed: Optional[str], before: Optional[dt.date], after: Optional[dt.date],
               start: Optional[dt.date], end: Optional[dt.date]) -> tuple[Optional[dt.date], Optional[str]]:
    """Returns (date, None) when acceptable, else (None, reason)."""
    if not proposed or not proposed.strip():
        return None, "empty"
    try:
        d = dt.date.fromisoformat(proposed.strip())
    except ValueError:
        return None, "malformed"

    # every number visible in the text must be a part of the proposed date
    allowed = {str(d.day), f"{d.day:02d}", str(d.month), f"{d.month:02d}", str(d.year), f"{d.year % 100:02d}"}
    if any(tok not in allowed for tok in re.findall(r"\d+", text)):
        return None, "contradicts_text"
    # a month written in letters must be close to the proposed month's abbreviation
    letters = re.sub(r"[^A-Za-z]", "", text).casefold()
    if letters and len(re.findall(r"\d+", text)) < 3:
        abbr = d.strftime("%b").casefold()
        if not (abbr.startswith(letters) or edit_distance(letters, abbr) <= 1):
            return None, "contradicts_text"

    if before is not None and d < before:
        return None, "out_of_order"
    if after is not None and d > after:
        return None, "out_of_order"
    if start is not None and end is not None and not (start <= d <= end):
        return None, "outside_period"
    return d, None
