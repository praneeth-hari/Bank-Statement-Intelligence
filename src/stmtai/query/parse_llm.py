"""Ask a local model to turn a question into a ``Query``. Its answer is only ever parsed and validated, never run.

The model is told what the data contains (today's date, the transaction types, the payee names that occur), must
answer in a fixed JSON shape, and may say the question cannot be answered. Anything that does not validate into a
``Query`` is a refusal. It cannot reach the rows, write SQL, or execute anything.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from ..llm.client import LLMUnavailable
from .data import Row
from .model import CATEGORIES, Query
from .parse_rules import Parsed

SCHEMA = {
    "type": "object",
    "properties": {
        "answerable": {"type": "boolean"},
        "aggregate": {"type": "string", "enum": ["sum", "count", "max", "min", "avg", "list", "last"]},
        "measure": {"type": "string", "enum": ["debit", "credit", "net", "balance"]},
        "date_from": {"type": "string"}, "date_to": {"type": "string"},
        "categories": {"type": "array", "items": {"type": "string", "enum": list(CATEGORIES)}},
        "text": {"type": "array", "items": {"type": "string"}},
        "min_amount": {"type": "string"}, "max_amount": {"type": "string"},
        "group_by": {"type": "string", "enum": ["", "month", "category", "payee"]},
        "limit": {"type": "integer"},
        "order": {"type": "string", "enum": ["desc", "asc"]},
    },
    "required": ["answerable"],
}

SYSTEM = """You translate questions about a person's bank transactions into a JSON query. You never answer the question yourself.

Fields:
- answerable: false if the question is not about these transactions (weather, advice, predictions, opinions). Then leave the rest empty.
- aggregate: sum (total), count (how many), max (largest single), min (smallest single), avg (average), list (show the individual transactions), last (the balance at the end of the period).
- measure: debit (money spent, withdrawals), credit (money received, salary, deposits), net (credits minus debits, all transactions), balance (account balance).
- date_from, date_to: YYYY-MM-DD, inclusive, or empty. A month means its first to its last day. Use the year the data contains.
- categories: any of upi, imps, neft, pos (card swipes), atm (cash withdrawals), emi (loan instalments), salary, charges (bank fees), interest.
- text: words that must appear in the description, for a merchant or person's name. Use the exact spelling from the list of names when one matches.
- min_amount, max_amount: numbers as text, or empty.
- group_by: month, category, payee, or empty. Use it for "per month", "by category", "which merchants".
- limit: how many items for list or grouped answers (default 10). order: desc for largest first, asc for smallest first.

Examples (invented data):
Q: how much did I spend at Decathlon in June 2025 -> {"answerable":true,"aggregate":"sum","measure":"debit","date_from":"2025-06-01","date_to":"2025-06-30","text":["decathlon"]}
Q: number of salary credits -> {"answerable":true,"aggregate":"count","measure":"credit","categories":["salary"]}
Q: split my spending by type -> {"answerable":true,"aggregate":"sum","measure":"debit","group_by":"category"}
Q: will I be able to afford a scooter -> {"answerable":false}"""


def _date(s: Any) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(str(s).strip()) if s and str(s).strip() else None
    except ValueError:
        return None


def _amount(s: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(s).replace(",", "").strip()) if s not in (None, "") and str(s).strip() else None
    except InvalidOperation:
        return None


def to_query(obj: dict[str, Any]) -> Query:
    return Query(
        aggregate=obj["aggregate"], measure=obj.get("measure") or "debit", date_from=_date(obj.get("date_from")),
        date_to=_date(obj.get("date_to")), categories=obj.get("categories") or [], text=obj.get("text") or [],
        min_amount=_amount(obj.get("min_amount")), max_amount=_amount(obj.get("max_amount")),
        group_by=obj.get("group_by") or None, limit=int(obj.get("limit") or 10), order=obj.get("order") or "desc")


def parse(question: str, rows: list[Row], client, today: Optional[dt.date] = None) -> Parsed:
    today = today or max((r.date for r in rows), default=dt.date.today())
    years = sorted({r.date.year for r in rows})
    names = [n for n, _ in Counter(r.payee for r in rows if r.payee).most_common(30)]
    context = (f"Today is {today}. The data covers {min((r.date for r in rows), default=today)} to "
               f"{max((r.date for r in rows), default=today)} (years {', '.join(map(str, years)) or 'none'}).\n"
               f"Names that occur in descriptions: {', '.join(names) or 'none'}.")
    try:
        reply = client.chat_json(SYSTEM, f"{context}\nQ: {question}", SCHEMA, max_tokens=300)
    except LLMUnavailable as exc:
        return Parsed(reason=f"The language model is not available ({exc})")
    if not isinstance(reply, dict) or not reply.get("answerable"):
        return Parsed(reason="That does not look like a question about the transactions.")
    if "aggregate" not in reply:
        return Parsed(reason="The model did not say what to compute.")
    try:
        return Parsed(query=to_query(reply))
    except (ValueError, TypeError, KeyError) as exc:
        return Parsed(reason=f"The model's query was not valid ({exc}).")
