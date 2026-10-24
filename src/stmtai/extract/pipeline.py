"""Single entry point: extract a statement PDF and score every field."""

from __future__ import annotations

from pathlib import Path

from .digital import extract_digital
from .models import ExtractedStatement
from .scoring import score


def extract_pdf(path: str | Path) -> ExtractedStatement:
    """Extract from a digital PDF and score it.

    Scanned PDFs raise ``NotDigitalError``; the OCR path is added in the next step.
    """
    return score(extract_digital(path))
