"""Single entry point: extract a statement PDF (digital or scanned) and score every field."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .digital import NotDigitalError, extract_digital
from .models import ExtractedStatement
from .scoring import score

DEFAULT_CACHE = Path("data/ocr_cache")


def extract_pdf(path: str | Path, ocr: bool = True, ocr_backend=None,
                cache_dir: Optional[Path] = DEFAULT_CACHE, preprocess: str = "none") -> ExtractedStatement:
    """Use the text layer when there is one; otherwise fall back to OCR (unless ``ocr=False``)."""
    try:
        return score(extract_digital(path))
    except NotDigitalError:
        if not ocr:
            raise
    from .scanned import extract_scan  # imported lazily so the digital path never needs OCR installed

    return score(extract_scan(path, backend=ocr_backend, cache_dir=cache_dir, preprocess=preprocess))
