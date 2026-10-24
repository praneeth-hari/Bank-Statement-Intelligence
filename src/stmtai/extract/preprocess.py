"""Image cleanup applied before OCR.

Scans lose accuracy to three things that are cheap to undo: uneven lighting, sensor/paper noise and low
contrast. Recipes are named, deterministic step lists so OCR results can be cached per recipe and the
recipes compared on the same labelled scans. More processing is not automatically better: aggressive
contrast stretching fattens strokes until neighbouring digits fuse, which hurts recognition even though the
image looks cleaner to a person. Recipes are therefore chosen by measurement (see the README).

``preprocess`` returns ``(image, scale)``. If an upscale was applied, OCR coordinates must be divided by
``scale`` to get back to the original pixel grid (``ocr_pdf`` does this).
"""

from __future__ import annotations

import cv2
import numpy as np


def flatten_illumination(img: np.ndarray, kernel: int = 51) -> np.ndarray:
    """Divide out the slowly varying background (shadows, uneven lamp) so paper becomes uniformly white."""
    k = kernel | 1
    background = cv2.medianBlur(cv2.dilate(img, np.ones((7, 7), np.uint8)), k)
    return cv2.divide(img, background, scale=255)


def stretch_contrast(img: np.ndarray, lo: float = 1.0, hi: float = 99.0) -> np.ndarray:
    a, b = np.percentile(img, [lo, hi])
    if b - a < 1:
        return img
    return np.clip((img.astype(np.float32) - a) * 255.0 / (b - a), 0, 255).astype(np.uint8)


def gamma(img: np.ndarray, g: float = 1.6) -> np.ndarray:
    """g > 1 darkens mid-tones a little without fattening strokes the way a hard stretch does."""
    table = ((np.arange(256) / 255.0) ** g * 255).astype(np.uint8)
    return cv2.LUT(img, table)


def denoise(img: np.ndarray, strength: int = 12) -> np.ndarray:
    return cv2.fastNlMeansDenoising(img, None, h=strength, templateWindowSize=7, searchWindowSize=21)


def median(img: np.ndarray, size: int = 3) -> np.ndarray:
    return cv2.medianBlur(img, size)


def unsharp(img: np.ndarray, sigma: float = 1.2, amount: float = 0.9) -> np.ndarray:
    blur = cv2.GaussianBlur(img, (0, 0), sigma)
    return cv2.addWeighted(img, 1.0 + amount, blur, -amount, 0)


def upscale(img: np.ndarray, factor: float = 1.5) -> np.ndarray:
    return cv2.resize(img, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)


# name -> ordered steps. 'up' is handled separately because it changes the coordinate scale.
RECIPES: dict[str, list[str]] = {
    "none": [],
    "flat": ["flatten"],
    "flat_gamma": ["flatten", "gamma"],
    "flat_median": ["flatten", "median"],
    "flat_denoise": ["flatten", "denoise"],
    "flat_denoise_gamma": ["flatten", "denoise", "gamma"],
    "flat_up": ["flatten", "up"],
    "flat_denoise_up": ["flatten", "denoise", "up"],
    "clean": ["flatten", "denoise", "stretch"],  # kept for comparison: the over-aggressive recipe
}
VARIANTS = tuple(RECIPES)
_UPSCALE = 1.5

_STEPS = {
    "flatten": flatten_illumination,
    "stretch": stretch_contrast,
    "gamma": gamma,
    "denoise": denoise,
    "median": median,
    "sharpen": unsharp,
}


def preprocess(img: np.ndarray, variant: str = "none") -> tuple[np.ndarray, float]:
    if variant not in RECIPES:
        raise ValueError(f"unknown preprocessing variant: {variant} (choose from {', '.join(VARIANTS)})")
    out, scale = img, 1.0
    for step in RECIPES[variant]:
        if step == "up":
            out, scale = upscale(out, _UPSCALE), scale * _UPSCALE
        else:
            out = _STEPS[step](out)
    return out, scale
