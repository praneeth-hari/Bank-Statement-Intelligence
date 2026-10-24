"""Question in, answer out: rules first, an optional model second, always shown how it was understood."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from . import parse_llm, parse_rules
from .data import Row
from .engine import Answer, run
from .model import Query, describe


@dataclass
class Result:
    question: str
    answered: bool
    parser: Optional[str] = None                 # "rules" or "model"
    query: Optional[Query] = None
    interpretation: Optional[str] = None
    notes: list[str] = field(default_factory=list)
    answer: Optional[Answer] = None
    reason: Optional[str] = None


def ask(question: str, rows: list[Row], client: Any = None, today: Optional[dt.date] = None,
        mode: Literal["rules", "model", "auto"] = "auto") -> Result:
    """``auto``: rules, then the model for what the rules refused. ``rules`` / ``model``: that parser alone."""
    if not question or not question.strip() or len(question) > 300:
        return Result(question, False, reason="Ask a question of up to 300 characters.")
    parsed, used = None, None
    if mode in ("rules", "auto"):
        parsed, used = parse_rules.parse(question, rows, today), "rules"
    if (mode == "model" or (mode == "auto" and parsed is not None and parsed.query is None)) and client is not None:
        refused_by_rules = parsed.reason if parsed else None
        parsed, used = parse_llm.parse(question, rows, client, today), "model"
        if parsed.query is None and refused_by_rules and "not available" in (parsed.reason or ""):
            parsed.reason = refused_by_rules
    if parsed is None or parsed.query is None:
        return Result(question, False, parser=used, reason=(parsed.reason if parsed else "No parser is available."))
    return Result(question, True, parser=used, query=parsed.query, interpretation=describe(parsed.query),
                  notes=parsed.notes, answer=run(parsed.query, rows))
