"""Extract a statement from a scanned (image-only) PDF via OCR."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .digital import OCR, Word, extract_from_pages, group_lines
from .models import ExtractedStatement
from .ocr import DEFAULT_DPI, OCRBackend, get_backend, ocr_pdf, tokenize_page


def extract_scan(path: str | Path, backend: Optional[OCRBackend] = None, dpi: int = DEFAULT_DPI,
                 cache_dir: Optional[Path] = None, preprocess: str = "none") -> ExtractedStatement:
    path = Path(path)
    backend = backend or get_backend("rapidocr")
    pages_raw = ocr_pdf(path, backend, dpi=dpi, cache_dir=cache_dir, preprocess=preprocess)

    pages = []
    skews = []
    confidences = []
    for pno, page in enumerate(pages_raw):
        tokens, skew = tokenize_page(page)
        skews.append(round(skew, 2))
        words = [Word(t.x0, t.y0, t.x1, t.y1, t.text, pno, conf=t.conf, display=t.display) for t in tokens]
        confidences += [t.conf for t in tokens]
        pages.append(group_lines(words, OCR))

    meta = {
        "ocr_engine": backend.name,
        "preprocess": preprocess,
        "dpi": dpi,
        "skew_degrees": skews,
        "mean_ocr_confidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
    }
    return extract_from_pages(pages, OCR, path.name, meta=meta)
