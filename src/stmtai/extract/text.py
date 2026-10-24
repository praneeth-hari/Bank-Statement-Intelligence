"""Format knowledge for transaction descriptions, used only on OCR output.

OCR confidence says how sure the engine is, not whether it is right: PP-OCR reads ``UPI/`` as ``UP/`` or
``UPV`` consistently and with high confidence, so no confidence threshold can catch it. A format check can.
Indian payment rails print a fixed prefix followed by a fixed-length reference number, so a mangled prefix in
front of a clean digit run can be restored, and the run can be checked against the reference column.

Scope, stated plainly: this is a small lexicon of payment-rail prefixes (UPI, IMPS). It is domain knowledge
about Indian statements, not tuning to the synthetic merchants, and every change it makes is flagged
``prefix_snapped`` so the reviewer can see it.
"""

from __future__ import annotations

import re
from typing import Optional

# (canonical prefix, pattern for the damaged prefix). The lookahead requires the digit run that follows a
# genuine rail reference, which keeps this from rewriting ordinary words that happen to start with 'UP'.
# The damaged-prefix quantifier is lazy on purpose: ``UPV160733754330`` is ``UPI/`` plus a 12-digit reference
# (OCR merged ``I/`` into ``V``), and a greedy match swallowed the first digit of the reference as a "1" glyph.
_RAILS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("UPI/", re.compile(r"^U[PF][A-Za-z1|!]{0,2}?[/\\\s-]?(?=\d{10,13}(?!\d))")),
    ("IMPS/", re.compile(r"^I[MN][PF][S5]?[/\\\s-]?(?=\d{10,13}(?!\d))")),
)
_DIGIT_RUN = re.compile(r"\d{10,}")


def snap_prefix(text: str) -> tuple[str, Optional[str]]:
    """Restore a damaged payment-rail prefix. Returns (text, canonical prefix used or None if unchanged)."""
    stripped = text.strip()
    for canonical, pattern in _RAILS:
        m = pattern.match(stripped)
        if m:
            fixed = canonical + stripped[m.end():]
            return fixed, (canonical if fixed != stripped else None)
    return text, None


def digit_runs(text: str) -> list[str]:
    return _DIGIT_RUN.findall(text)


def reference_matches(description: str, ref: str) -> bool:
    """The reference column and the number inside the description are two reads of the same digits."""
    ref_digits = "".join(ch for ch in ref if ch.isdigit())
    return len(ref_digits) >= 10 and any(ref_digits == run or ref_digits in run for run in digit_runs(description))
