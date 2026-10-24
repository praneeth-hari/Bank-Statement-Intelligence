"""OCR backends, an on-disk result cache, and page geometry.

A backend turns a page image into text segments: ``(quad, text, confidence)`` where ``quad`` is four
``(x, y)`` pixel corners. Everything after that is engine-independent:

1. **cache** raw results by file hash, engine and DPI, so evaluation is reproducible and an expensive
   engine (for example a GPU vision-language model) can be run once elsewhere and replayed here;
2. **deskew**: estimate the page rotation from the segments' own slopes and rotate the coordinates back,
   so columns line up vertically again (a 3 degree skew moves text ~40pt sideways over a page);
3. **tokenize** segments into words with interpolated x positions, splitting merged ``Dr``/``Cr`` suffixes;
4. convert pixels to PDF points so the thresholds tuned on digital PDFs still apply.

Each word keeps its original (un-deskewed) box for display, so the review UI highlights the right spot
on the page image the reviewer actually sees.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

import numpy as np

Segment = tuple[list[list[float]], str, float]  # quad (4 x [x, y]) in pixels, text, confidence 0..1

DEFAULT_DPI = 200
CACHE_VERSION = 1


class OCRBackend(Protocol):
    name: str

    def read(self, image: np.ndarray) -> list[Segment]:
        ...


class OCRUnavailableError(RuntimeError):
    """The OCR engine is not installed."""


# --------------------------------------------------------------------------- RapidOCR
class RapidOCRBackend:
    """PP-OCRv3 models through ONNX Runtime: CPU only, installs with pip, no system binaries."""

    name = "rapidocr"

    def __init__(self) -> None:
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise OCRUnavailableError(
                "RapidOCR is not installed. Run: pip install -e \".[ocr]\""
            ) from exc
        self._engine = RapidOCR()

    def read(self, image: np.ndarray) -> list[Segment]:
        # text_score=0 keeps low-confidence text: dropping it here would silently delete exactly the cells
        # the review step needs to see.
        result, _ = self._engine(image, text_score=0.0)
        segments: list[Segment] = []
        for quad, text, conf in result or []:
            text = str(text).strip()
            if text:
                segments.append(([[float(x), float(y)] for x, y in quad], text, float(conf)))
        return segments


def get_backend(name: str = "rapidocr") -> OCRBackend:
    if name == "rapidocr":
        return RapidOCRBackend()
    raise ValueError(f"unknown OCR backend: {name}")


# --------------------------------------------------------------------------- cache
def _file_hash(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


@dataclass
class OCRPage:
    width_px: int
    height_px: int
    dpi: int
    segments: list[Segment]


def ocr_pdf(path: str | Path, backend: OCRBackend, dpi: int = DEFAULT_DPI,
            cache_dir: Optional[Path] = None, preprocess: str = "none") -> list[OCRPage]:
    """OCR every page of a PDF, using ``cache_dir`` when given.

    ``preprocess`` names an image-cleanup recipe (see ``preprocess.py``). Coordinates are always returned
    on the original rasterised page, so downstream geometry does not depend on the recipe.
    """
    from ..synth.scan import rasterize  # local import keeps OpenCV/PyMuPDF optional for callers
    from .preprocess import preprocess as clean

    path = Path(path)
    cache_file = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        variant = "" if preprocess == "none" else f"_{preprocess}"  # keeps pre-existing cache entries valid
        cache_file = cache_dir / f"{_file_hash(path)}_{backend.name}_{dpi}{variant}_v{CACHE_VERSION}.json"
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return [OCRPage(p["w"], p["h"], p["dpi"], [(s[0], s[1], s[2]) for s in p["segments"]])
                    for p in data["pages"]]

    pages = []
    for image in rasterize(path, dpi):
        h, w = image.shape[:2]
        cleaned, scale = clean(image, preprocess)
        segments = backend.read(cleaned)
        if scale != 1.0:
            segments = [([[x / scale, y / scale] for x, y in quad], text, conf) for quad, text, conf in segments]
        pages.append(OCRPage(w, h, dpi, segments))

    if cache_file is not None:
        payload = {"source": path.name, "engine": backend.name, "dpi": dpi,
                   "pages": [{"w": p.width_px, "h": p.height_px, "dpi": p.dpi,
                              "segments": [[q, t, c] for q, t, c in p.segments]} for p in pages]}
        cache_file.write_text(json.dumps(payload), encoding="utf-8")
    return pages


# --------------------------------------------------------------------------- geometry
def estimate_skew(segments: list[Segment]) -> float:
    """Page rotation in radians, from the top edges of wide text segments (median, so outliers don't matter)."""
    angles = []
    weights = []
    for quad, _, _ in segments:
        (x0, y0), (x1, y1) = quad[0], quad[1]
        width = math.hypot(x1 - x0, y1 - y0)
        height = math.hypot(quad[3][0] - x0, quad[3][1] - y0)
        if width > 3 * max(height, 1.0) and width > 40:
            angles.append(math.atan2(y1 - y0, x1 - x0))
            weights.append(width)
    if not angles:
        return 0.0
    order = np.argsort(angles)
    cumulative = np.cumsum(np.array(weights)[order])
    median_index = order[int(np.searchsorted(cumulative, cumulative[-1] / 2))]
    return float(angles[median_index])


def _rotate(points: np.ndarray, angle: float, cx: float, cy: float) -> np.ndarray:
    c, s = math.cos(-angle), math.sin(-angle)
    x, y = points[:, 0] - cx, points[:, 1] - cy
    return np.stack([x * c - y * s + cx, x * s + y * c + cy], axis=1)


_SUFFIX_SPLIT = re.compile(r"^(.*\d)\s*(Dr|Cr|DR|CR|dr|cr)\.?$")


@dataclass
class OCRToken:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    conf: float
    display: tuple[float, float, float, float]  # original box in points (for highlighting on the scan)


def tokenize_page(page: OCRPage) -> tuple[list[OCRToken], float]:
    """Deskew, split segments into words, convert to points. Returns (tokens, skew in degrees)."""
    scale = 72.0 / page.dpi
    angle = estimate_skew(page.segments)
    cx, cy = page.width_px / 2, page.height_px / 2
    tokens: list[OCRToken] = []

    for quad, text, conf in page.segments:
        pts = np.array(quad, dtype=float)
        disp = (pts[:, 0].min() * scale, pts[:, 1].min() * scale, pts[:, 0].max() * scale, pts[:, 1].max() * scale)
        rot = _rotate(pts, angle, cx, cy)
        x0, x1 = rot[:, 0].min() * scale, rot[:, 0].max() * scale
        y0, y1 = rot[:, 1].min() * scale, rot[:, 1].max() * scale

        parts = text.split()
        if len(parts) == 1:  # split a merged suffix like '5,373.14Dr' so the suffix is its own word
            m = _SUFFIX_SPLIT.match(parts[0])
            if m:
                parts = [m.group(1), m.group(2)]
        total = sum(len(p) for p in parts) + max(len(parts) - 1, 0)
        cursor = 0
        width = x1 - x0
        for part in parts:
            start = x0 + width * cursor / max(total, 1)
            end = x0 + width * (cursor + len(part)) / max(total, 1)
            tokens.append(OCRToken(start, y0, end, y1, part, conf, disp))
            cursor += len(part) + 1
    return tokens, math.degrees(angle)
