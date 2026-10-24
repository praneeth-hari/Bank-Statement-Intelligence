"""LLM fallback: propose corrections for the cells the arithmetic cannot settle.

**What it is for.** After scoring, most doubtful cells have a suggestion from the running-balance chain. The ones
that do not are text the OCR damaged by a character or two (a merchant or a person's name) and dates it could not
parse. Arithmetic says nothing about those, which is where a language model can help: it knows what ``IRCTC`` or
``DECATHLON`` look like when the scan says ``RCTC`` or ``DECATHL.N``.

**What it is not.** It never touches money, reference numbers or the digits of anything, it never overwrites a
value, and its output is shown as a suggestion only after ``stmtai.llm.validate`` has checked it against the
document (digits unchanged, few edits, date between its neighbours and inside the period). A cell it fills is
flagged ``llm_suggested`` so the reviewer and the metrics can tell it apart from an arithmetic suggestion.

**Failure is quiet.** If Ollama is not running, the statement is still extracted and scored exactly as before;
``ext.meta['llm']`` records why nothing was proposed.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from typing import Any, Callable, Iterable, Optional

from ..extract.models import ExtractedStatement
from ..extract.scoring import review_items, score
from .client import LLMUnavailable
from .rules import date_head, date_rule, description_rule
from .validate import check_date, check_description
from .vocab import Vocabulary, hints_for, vocab_rule

FLAG = "llm_suggested"
RULE_FLAG = "rule_suggested"
TEXT_FIELDS = ("description",)
DATE_FIELDS = ("date", "value_date")

DESCRIPTION_SYSTEM = """You repair OCR mistakes in transaction descriptions from Indian bank statements.
Each item is the text an OCR engine read from a scanned statement. Return the text as it most likely appears on the page.

Rules:
- Change as little as possible, usually one or two characters: a letter misread or dropped, or '.' ':' '/' read where there was a space.
- Never change any digit. Never invent digits.
- Keep the structure. Payment descriptions look like UPI/<12 digits>/<NAME> or IMPS/<12 digits>/<NAME>. A missing '/' before the name may be restored.
- <NAME> is a merchant (for example SWIGGY) or a person's first name and surname, in capitals. Put a space between first name and surname when it was lost.
- An item may list "seen_names": names printed more than once elsewhere on the same statement. If the text is a damaged version of one of them, answer with that name.
- If you are not sure, return the text unchanged.

Examples:
UPI/310045678901/DECATHL.N -> UPI/310045678901/DECATHLON
UPI/290011223344/ROHANMEHRA -> UPI/290011223344/ROHAN MEHRA
IMPS/660011223344/ANJALIKU/MAR -> IMPS/660011223344/ANJALI KUMAR
UPI/118899001122/NYKAA -> UPI/118899001122/NYKAA"""

DESCRIPTION_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
        "required": ["id", "text"]}}},
    "required": ["items"],
}

DATE_SYSTEM = """You repair transaction dates that OCR damaged on Indian bank statements.
Each item gives the text that was read, the dates of the transactions just before and after it, and the statement period.
Answer with the date as YYYY-MM-DD. The date must fall between the neighbouring dates and inside the period, and every number visible in the text must be part of it.
If you cannot tell, answer with an empty string."""

DATE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "integer"}, "date": {"type": "string"}},
        "required": ["id", "date"]}}},
    "required": ["items"],
}


def _neighbour_dates(ext: ExtractedStatement, row: int) -> tuple[Optional[dt.date], Optional[dt.date]]:
    dates = [t.value("date") for t in ext.transactions]
    before = next((d for d in reversed(dates[:row]) if d is not None), None)
    after = next((d for d in dates[row + 1:] if d is not None), None)
    return before, after


def candidates(ext: ExtractedStatement) -> list[tuple[int, str]]:
    """(row, field) of every cell the model may be asked about: flagged, no arithmetic suggestion, and not money."""
    scored = score(ext.model_copy(deep=True))
    out = []
    for row, name, _conf, _flags in review_items(scored):
        if row is None:
            continue
        fv = scored.transactions[row].fields[name]
        if fv.suggestion is not None or "suggest_clear" in fv.flags:
            continue
        if name in TEXT_FIELDS and fv.value:
            out.append((row, name))
        elif name in DATE_FIELDS and fv.value is None and fv.text:
            out.append((row, name))  # unparseable only; a parsed date that breaks the order is a data conflict
    return out


def _trace(trace: Optional[list[dict]], row: int, field: str, read: Any, answer: Optional[str],
           rejected: Optional[str], source: str = "llm") -> None:
    if trace is not None:
        trace.append({"row": row, "field": field, "read": read, "answer": answer, "rejected": rejected, "source": source})


def apply_rules(ext: ExtractedStatement, trace: Optional[list[dict]] = None,
                known: Iterable[str] = ()) -> ExtractedStatement:
    """Deterministic proposals for the same cells the model would be asked about; see ``stmtai.llm.rules``.

    ``known`` is descriptions from statements a reviewer already approved: the names in them are trusted vocabulary,
    on top of the names this statement repeats.
    """
    start, end = ext.header_value("period_start"), ext.header_value("period_end")
    proposed, rejected = 0, Counter()
    cells = candidates(ext)
    vocab = Vocabulary([*known, *(str(t.value("description") or "") for t in ext.transactions)])
    for row, name in cells:
        fv = ext.transactions[row].fields[name]
        if name in TEXT_FIELDS:
            read = str(fv.value)
            repaired = description_rule(read) or read
            answer = vocab_rule(repaired, vocab) or (repaired if repaired != read else None)
            if answer is None:
                continue
            reason = check_description(read, answer, lookalikes=True)
            _trace(trace, row, name, fv.value, answer, reason, "rule")
            if reason:
                rejected[reason] += 1
                continue
            fv.suggestion = answer
        else:
            head = date_head(fv.text)
            if head is None:
                continue
            before, after = _neighbour_dates(ext, row)
            answer = date_rule(fv.text, before, after, start, end)
            if answer is None:
                continue
            d, reason = check_date(head, answer, before, after, start, end)
            _trace(trace, row, name, fv.text, answer, reason, "rule")
            if reason:
                rejected[reason] += 1
                continue
            fv.suggestion = d
        if RULE_FLAG not in fv.flags:
            fv.flags.append(RULE_FLAG)
        proposed += 1
    ext.meta["rules"] = {"asked": len(cells), "proposed": proposed, "rejected": dict(rejected)}
    return ext


def suggest(ext: ExtractedStatement, client=None, **kwargs) -> ExtractedStatement:
    """Rules first, then the model for whatever the rules left alone. ``client=None`` runs the rules only."""
    apply_rules(ext, trace=kwargs.get("trace"), known=kwargs.get("known", ()))
    if client is not None:
        llm_fallback(ext, client, **kwargs)
    return ext


def _batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _ask(client, system: str, payload: list[dict], schema: dict) -> dict[int, str]:
    user = "\n".join(json.dumps(p, ensure_ascii=False) for p in payload)
    reply = client.chat_json(system, user, schema)
    key = "text" if "text" in schema["properties"]["items"]["items"]["properties"] else "date"
    out: dict[int, str] = {}
    for item in (reply or {}).get("items", []):
        if isinstance(item, dict) and isinstance(item.get("id"), int) and isinstance(item.get(key), str):
            out[item["id"]] = item[key]
    return out


def llm_fallback(ext: ExtractedStatement, client, batch_size: int = 6, max_cells: int = 120,
                 on_batch: Optional[Callable[[int, int], None]] = None,
                 trace: Optional[list[dict]] = None, known: Iterable[str] = ()) -> ExtractedStatement:
    """Attach validated model suggestions to ``ext`` in place and return it. Safe to call on a raw or scored extraction.

    ``trace``, when given, receives one record per cell asked: what the model answered and why it was or was not
    accepted. The evaluation uses it to show what the validators prevented.
    """
    cells = candidates(ext)[:max_cells]
    stats: dict[str, Any] = {"model": getattr(client, "name", "unknown"), "status": "ok", "asked": len(cells),
                             "proposed": 0, "rejected": {}, "unanswered": 0}
    rejected: Counter[str] = Counter()
    start, end = ext.header_value("period_start"), ext.header_value("period_end")
    calls_before, seconds_before = getattr(client, "calls", 0), getattr(client, "seconds", 0.0)

    try:
        texts = [c for c in cells if c[1] in TEXT_FIELDS]
        dates = [c for c in cells if c[1] in DATE_FIELDS]
        done = 0
        for batch in _batches(texts, batch_size):
            payload = []
            vocab = Vocabulary([*known, *(str(t.value("description") or "") for t in ext.transactions)])
            for i, (row, name) in enumerate(batch):
                t = ext.transactions[row]
                item = {"id": i, "text": t.fields[name].value}
                if t.value("ref"):
                    item["reference_column"] = t.value("ref")
                hints = hints_for(str(t.fields[name].value), vocab)
                if hints:
                    item["seen_names"] = hints
                payload.append(item)
            answers = _ask(client, DESCRIPTION_SYSTEM, payload, DESCRIPTION_SCHEMA)
            for i, (row, name) in enumerate(batch):
                fv = ext.transactions[row].fields[name]
                if i not in answers:
                    stats["unanswered"] += 1
                    _trace(trace, row, name, fv.value, None, "unanswered")
                    continue
                reason = check_description(str(fv.value), answers[i])
                _trace(trace, row, name, fv.value, answers[i], reason)
                if reason:
                    rejected[reason] += 1
                    continue
                fv.suggestion = answers[i].strip()
                if FLAG not in fv.flags:
                    fv.flags.append(FLAG)
                stats["proposed"] += 1
            done += len(batch)
            if on_batch:
                on_batch(done, len(cells))
        for batch in _batches(dates, batch_size):
            payload = []
            for i, (row, name) in enumerate(batch):
                before, after = _neighbour_dates(ext, row)
                payload.append({"id": i, "text": ext.transactions[row].fields[name].text,
                                "previous_date": before.isoformat() if before else None,
                                "next_date": after.isoformat() if after else None,
                                "period": f"{start} to {end}" if start and end else None})
            answers = _ask(client, DATE_SYSTEM, payload, DATE_SCHEMA)
            for i, (row, name) in enumerate(batch):
                fv = ext.transactions[row].fields[name]
                if i not in answers:
                    stats["unanswered"] += 1
                    _trace(trace, row, name, fv.text, None, "unanswered")
                    continue
                before, after = _neighbour_dates(ext, row)
                d, reason = check_date(fv.text, answers[i], before, after, start, end)
                _trace(trace, row, name, fv.text, answers[i], reason)
                if reason:
                    rejected[reason] += 1
                    continue
                fv.suggestion = d
                if FLAG not in fv.flags:
                    fv.flags.append(FLAG)
                stats["proposed"] += 1
            done += len(batch)
            if on_batch:
                on_batch(done, len(cells))
    except LLMUnavailable as exc:
        stats["status"] = "unavailable"
        stats["error"] = str(exc)

    stats["rejected"] = dict(rejected)
    stats["calls"] = getattr(client, "calls", 0) - calls_before
    stats["seconds"] = round(getattr(client, "seconds", 0.0) - seconds_before, 2)
    ext.meta["llm"] = stats
    return ext
