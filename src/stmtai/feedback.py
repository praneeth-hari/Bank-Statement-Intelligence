"""Measure the confidence scores against what human reviewers actually did.

On synthetic data the ground truth is known, so ``evaluate`` can say exactly how good the flags are. On
documents a person has reviewed there is no ground truth file, but there is something almost as good: a log
of what the reviewer was shown (the value, its confidence, whether it was flagged) and what they did with it
(confirmed, corrected, accepted a suggestion). This module turns that log into the same style of metrics.

Read the numbers with their blind spot in mind: a reviewer only looks at flagged cells, so *missed errors*
(corrections on cells that were not flagged) are a lower bound, not the true miss rate.
"""

from __future__ import annotations

from typing import Optional


def _ratio(a: int, b: int) -> Optional[float]:
    return round(a / b, 4) if b else None


def _changed(c: dict) -> bool:
    if c["action"] == "confirm":
        return False
    return (c["new_value"] or "") != (c["original_value"] or "")


def summarize(corrections: list[dict]) -> dict:
    """``corrections`` are rows from the corrections table (latest action per cell counts)."""
    latest: dict[tuple, dict] = {}
    for c in corrections:
        latest[(c["statement_id"], c["row"], c["field"])] = c
    items = list(latest.values())

    def block(rows: list[dict]) -> dict:
        flagged = [c for c in rows if c["was_flagged"]]
        unflagged = [c for c in rows if not c["was_flagged"]]
        wrong_flagged = [c for c in flagged if _changed(c)]
        with_suggestion = [c for c in flagged if c["had_suggestion"]]
        return {
            "reviewed": len(rows),
            "flagged_reviewed": len(flagged),
            "flagged_actually_wrong": len(wrong_flagged),
            "flag_precision": _ratio(len(wrong_flagged), len(flagged)),
            "unflagged_corrected": sum(1 for c in unflagged if _changed(c)),
            "suggestions_offered": len(with_suggestion),
            "suggestions_accepted": sum(1 for c in with_suggestion if c["action"] == "accept_suggestion"),
            "suggestion_accept_rate": _ratio(sum(1 for c in with_suggestion if c["action"] == "accept_suggestion"),
                                             len(with_suggestion)),
        }

    fields = sorted({c["field"] for c in items})
    return {"overall": block(items), "by_field": {f: block([c for c in items if c["field"] == f]) for f in fields},
            "note": "unflagged_corrected is a lower bound: reviewers mostly look at flagged cells only."}
