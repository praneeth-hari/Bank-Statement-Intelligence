"""The Quality page's numbers: how far the confidence scores can be trusted, read from the saved evaluation reports.

Nothing here is computed on a person's real statements. Every figure comes from a report file written by one of
the evaluation commands on synthetic statements whose true values are known:

    reports/digital-metrics.json, reports/scan-{light,medium,heavy}/metrics.json   python -m stmtai.evaluate
    reports/quality-extras.json                                                    name repair and question answering

The last file holds the two result tables recorded in the README (steps 4 and 8), which come from runs that
need a local Ollama model and are not re-run here.

A missing report is reported as missing, never replaced by a plausible number.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

CONDITIONS = [("digital", "Digital PDF", "digital-metrics.json"),
              ("light", "Light scan", "scan-light/metrics.json"),
              ("medium", "Medium scan", "scan-medium/metrics.json"),
              ("heavy", "Heavy scan", "scan-heavy/metrics.json")]


def _read(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _condition(key: str, label: str, report: dict) -> Optional[dict[str, Any]]:
    o = report.get("overall") or {}
    r = o.get("review") or {}
    fields = r.get("fields_compared")
    if not fields:
        return None
    flagged, wrong, caught = r.get("fields_flagged", 0), r.get("wrong_fields", 0), r.get("wrong_caught_by_flags", 0)
    missed = wrong - caught
    by_field = r.get("by_field") or {}
    missed_by_field = {f: v["wrong"] - v["wrong_caught"] for f, v in by_field.items() if v.get("wrong", 0) > v.get("wrong_caught", 0)}
    return {
        "id": key, "label": label, "docs": o.get("docs"), "rows": o.get("rows_truth"),
        "fields": fields, "flagged": flagged, "wrong": wrong, "caught": caught, "missed": missed,
        "missed_by_field": dict(sorted(missed_by_field.items(), key=lambda kv: (-kv[1], kv[0]))),
        "accuracy": o.get("row_field_accuracy"), "flag_rate": r.get("flag_rate"),
        "error_recall": r.get("error_recall"),
        # every field lands in exactly one of four boxes; the page draws them as squares
        "outcomes": {"trusted_right": fields - flagged - missed, "flagged_fine": flagged - caught,
                     "flagged_wrong": caught, "trusted_wrong": missed},
    }


def load_quality(reports_dir: Path) -> dict[str, Any]:
    conditions = []
    for key, label, rel in CONDITIONS:
        report = _read(reports_dir / rel)
        c = _condition(key, label, report) if report else None
        if c:
            conditions.append(c)
    extras = _read(reports_dir / "quality-extras.json") or {}
    return {
        "available": bool(conditions),
        "conditions": conditions,
        "headline": next((c for c in conditions if c["id"] == "medium"), None),
        "names": extras.get("names", []),
        "questions": extras.get("questions", []),
        "extras_source": extras.get("source"),
        "threshold": 0.9,
        "note": "Measured on synthetic statements whose true values are known. Never on real documents.",
    }
