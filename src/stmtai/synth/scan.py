"""Turn a digital PDF into a degraded 'scan': an image-only PDF with no text layer.

Three severities simulate flatbed scans (light), phone photos of paper (medium) and
poor photocopies/faxes (heavy). Degradation is seeded, so the same input and seed
always produce the same output.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pymupdf

SEVERITIES = ("light", "medium", "heavy")


@dataclass(frozen=True)
class ScanParams:
    dpi: int
    rotation_deg: float  # max absolute skew
    perspective: float  # max corner jitter as a fraction of page size
    blur_sigma: float
    noise_sigma: float
    speckle: float  # fraction of pixels turned into dark specks
    shading: float  # strength of uneven lighting
    contrast: tuple[float, float]
    brightness: float  # max absolute brightness shift
    downscale: float  # 1.0 = none; <1 simulates resolution loss
    jpeg_quality: int
    paper: int  # background value used where the page is rotated/warped


PARAMS: dict[str, ScanParams] = {
    "light": ScanParams(200, 0.8, 0.0, 0.6, 4.0, 0.0, 0.03, (0.95, 1.05), 6, 1.0, 85, 245),
    "medium": ScanParams(180, 1.8, 0.004, 0.8, 8.0, 0.0004, 0.10, (0.82, 1.00), 12, 0.85, 70, 238),
    "heavy": ScanParams(150, 3.0, 0.008, 1.0, 13.0, 0.0010, 0.20, (0.70, 0.92), 18, 0.72, 55, 230),
}


def rasterize(pdf_path: Path, dpi: int) -> list[np.ndarray]:
    """Render each page to a grayscale uint8 array."""
    pages = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
            pages.append(np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w).copy())
    return pages


def degrade(img: np.ndarray, rng: np.random.Generator, severity: str) -> np.ndarray:
    p = PARAMS[severity]
    h, w = img.shape
    out = img.astype(np.float32)

    if p.downscale < 1.0:
        small = cv2.resize(out, (int(w * p.downscale), int(h * p.downscale)), interpolation=cv2.INTER_AREA)
        out = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    if p.blur_sigma > 0:
        out = cv2.GaussianBlur(out, (0, 0), p.blur_sigma)

    angle = float(rng.uniform(-p.rotation_deg, p.rotation_deg))
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    out = cv2.warpAffine(out, matrix, (w, h), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=float(p.paper))

    if p.perspective > 0:
        src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        jitter = rng.uniform(-p.perspective, p.perspective, (4, 2)) * np.float32([w, h])
        warp = cv2.getPerspectiveTransform(src, (src + jitter).astype(np.float32))
        out = cv2.warpPerspective(out, warp, (w, h), flags=cv2.INTER_LINEAR,
                                  borderMode=cv2.BORDER_CONSTANT, borderValue=float(p.paper))

    if p.shading > 0:  # uneven lighting: a smooth diagonal ramp
        ramp_y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
        ramp_x = np.linspace(0, 1, w, dtype=np.float32)[None, :]
        direction = rng.uniform(-1, 1, 2)
        ramp = direction[0] * ramp_y + direction[1] * ramp_x
        ramp = (ramp - ramp.min()) / max(float(ramp.max() - ramp.min()), 1e-6)
        out *= 1.0 - p.shading * ramp

    contrast = float(rng.uniform(*p.contrast))
    brightness = float(rng.uniform(-p.brightness, p.brightness))
    out = (out - 128.0) * contrast + 128.0 + brightness

    out += rng.normal(0.0, p.noise_sigma, out.shape).astype(np.float32)

    if p.speckle > 0:
        mask = rng.random(out.shape) < p.speckle
        out[mask] = rng.uniform(0, 90, int(mask.sum()))

    return np.clip(out, 0, 255).astype(np.uint8)


def make_scan(pdf_path: Path, out_path: Path, severity: str, seed: int) -> None:
    """Write an image-only PDF degraded from ``pdf_path``."""
    p = PARAMS[severity]
    rng = np.random.default_rng(seed)
    pages = rasterize(pdf_path, p.dpi)

    out = pymupdf.open()
    for img in pages:
        degraded = degrade(img, rng, severity)
        ok, jpeg = cv2.imencode(".jpg", degraded, [cv2.IMWRITE_JPEG_QUALITY, p.jpeg_quality])
        if not ok:
            raise RuntimeError("JPEG encoding failed")
        height_px, width_px = degraded.shape
        page = out.new_page(width=width_px * 72 / p.dpi, height=height_px * 72 / p.dpi)
        page.insert_image(page.rect, stream=jpeg.tobytes())
    out.save(out_path, deflate=True)
    out.close()
