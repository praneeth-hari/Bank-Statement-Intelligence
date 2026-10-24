"""Test helper: an OCR engine stand-in that replays the digital twin's words as OCR segments."""

from pathlib import Path

import fitz
import numpy as np

from stmtai.extract.ocr import DEFAULT_DPI


class ReplayBackend:
    """Pretends to be an OCR engine by returning the digital twin's words as segments (pixel coordinates)."""
    name = "replay"

    def __init__(self, digital_pdf: Path, mangle=None):
        doc = fitz.open(digital_pdf)
        k = DEFAULT_DPI / 72
        self.pages = []
        for page in doc:
            segs = []
            for x0, y0, x1, y1, text, *_ in page.get_text("words"):
                text = mangle(text) if mangle else text
                segs.append(([[x0 * k, y0 * k], [x1 * k, y0 * k], [x1 * k, y1 * k], [x0 * k, y1 * k]], text, 0.97))
            self.pages.append(segs)
        self.calls = 0

    def read(self, image: np.ndarray):
        segs = self.pages[min(self.calls, len(self.pages) - 1)]
        self.calls += 1
        return segs
