"""One CSV of every transaction on approved statements, for the Dashboard's download button.

Money leaves as the same two-decimal text the screen shows (never through floating point). Text that a
spreadsheet could run as a formula (it starts with = + - or @) gets a leading apostrophe, so opening the
file in Excel shows the text rather than executing it. Only description, reference and file name can hold
free text, so only those are touched.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Iterable, Optional

from ..query.data import Row, primary_category

COLUMNS = ["date", "description", "reference", "debit", "credit", "balance", "type", "statement", "statement_id", "row"]
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_text(value: Optional[str]) -> str:
    text = value or ""
    return "'" + text if text.startswith(_FORMULA_START) else text


def _money(x: Optional[Decimal]) -> str:
    return "" if x is None else f"{x:.2f}"


def transactions_csv(rows: Iterable[Row]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    for r in rows:
        w.writerow([r.date.isoformat(), safe_text(r.description), safe_text(r.ref), _money(r.debit), _money(r.credit),
                    _money(r.balance), primary_category(r.tags), safe_text(r.filename), r.statement_id, r.row])
    return buf.getvalue()
