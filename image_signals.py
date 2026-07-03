"""image_signals.py — deterministic, objective per-image signals (no LLM).

Three concerns, all pure functions that NEVER raise (return neutral/empty results on error,
matching the never-raise contract of text_generation.py):
  - extract_cv_signals: numpy fast path (reusing the np.asarray(img).astype(float32) idiom from
    citiview_project_lean/engine/renderer.py), with a Pillow-only fallback at lower confidence.
  - extract_metadata: EXIF DateTimeOriginal ONLY (tag 36867) — never filesystem mtime, never
    filenames. Frequently absent (PNGs carry no EXIF) — that is expected; metadata is secondary.
  - perceptual_hash / hamming: 64-bit average hash for near-duplicate detection.
"""
from datetime import datetime
from typing import Dict, Optional

from PIL import Image, ImageStat, ImageFilter

import lifecycle_taxonomy as tax
from analysis_schema import SignalReading

try:
    import numpy as _np
    _HAVE_NUMPY = True
except Exception:  # pragma: no cover - numpy is a declared dependency; belt-and-suspenders
    _HAVE_NUMPY = False

_EXIF_DATETIME_ORIGINAL = 36867  # EXIF tag DateTimeOriginal


# --- Objective CV signals -----------------------------------------------------------------
def extract_cv_signals(path: str) -> Dict[str, SignalReading]:
    """Return {brightness_mean, sharpness_var, edge_density, colorfulness} as cv-sourced
    SignalReadings in 0..1. Returns {} if the image cannot be read (engine tolerates absence)."""
    try:
        img = Image.open(path)
        img.load()
        img = img.convert("RGB")
    except Exception:
        return {}
    if _HAVE_NUMPY:
        return _cv_numpy(img)
    return _cv_pillow(img)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def _cv_numpy(img: Image.Image) -> Dict[str, SignalReading]:
    conf = tax.CV_CONFIDENCE
    arr = _np.asarray(img).astype(_np.float32)          # H x W x 3, 0..255
    lum = arr.mean(axis=2)                               # grayscale luminance
    brightness = float(lum.mean()) / 255.0
    # Laplacian variance as a sharpness / clutter-detail proxy.
    lap = (-4.0 * lum[1:-1, 1:-1] + lum[:-2, 1:-1] + lum[2:, 1:-1]
           + lum[1:-1, :-2] + lum[1:-1, 2:])
    sharpness = _clamp01(float(lap.var()) / tax.SHARPNESS_VAR_REF)
    # Gradient-magnitude mean as an edge-density (busy-frame) proxy.
    gy, gx = _np.gradient(lum)
    edge = _clamp01(float(_np.sqrt(gx * gx + gy * gy).mean()) / tax.EDGE_DENSITY_REF)
    # Hasler-Susstrunk colorfulness.
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    rg = r - g
    yb = 0.5 * (r + g) - b
    cf = float(_np.sqrt(rg.std() ** 2 + yb.std() ** 2)
               + 0.3 * _np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    colorfulness = _clamp01(cf / tax.COLORFULNESS_REF)
    return {
        "brightness_mean": SignalReading(brightness, conf, "cv"),
        "sharpness_var": SignalReading(sharpness, conf, "cv"),
        "edge_density": SignalReading(edge, conf, "cv"),
        "colorfulness": SignalReading(colorfulness, conf, "cv"),
    }


def _cv_pillow(img: Image.Image) -> Dict[str, SignalReading]:
    """numpy-free fallback — lower confidence, uses ImageStat / ImageFilter only."""
    conf = tax.CV_CONFIDENCE_FALLBACK
    lum = img.convert("L")
    brightness = ImageStat.Stat(lum).mean[0] / 255.0
    # variance of a FIND_EDGES pass approximates sharpness/detail.
    edges = lum.filter(ImageFilter.FIND_EDGES)
    est = ImageStat.Stat(edges)
    sharpness = _clamp01((est.var[0] if est.var else 0.0) / tax.SHARPNESS_VAR_REF)
    edge = _clamp01(est.mean[0] / tax.EDGE_DENSITY_REF)
    rgb_stat = ImageStat.Stat(img)
    # rough colorfulness proxy: spread of channel std-devs.
    stddev = rgb_stat.stddev
    colorfulness = _clamp01((max(stddev) - min(stddev)) / tax.COLORFULNESS_REF) if stddev else 0.0
    return {
        "brightness_mean": SignalReading(brightness, conf, "cv"),
        "sharpness_var": SignalReading(sharpness, conf, "cv"),
        "edge_density": SignalReading(edge, conf, "cv"),
        "colorfulness": SignalReading(colorfulness, conf, "cv"),
    }


# --- Metadata (EXIF DateTimeOriginal only) ------------------------------------------------
def extract_metadata(path: str) -> Dict[str, object]:
    """{'has_exif': bool, 'datetime_original': datetime|None}. Never mtime, never filename."""
    result = {"has_exif": False, "datetime_original": None}
    try:
        exif = Image.open(path).getexif()
    except Exception:
        return result
    if not exif:
        return result
    raw = exif.get(_EXIF_DATETIME_ORIGINAL)
    if raw is None:
        # some encoders store DateTimeOriginal only in the Exif IFD
        try:
            raw = exif.get_ifd(0x8769).get(_EXIF_DATETIME_ORIGINAL)
        except Exception:
            raw = None
    if not raw:
        return result
    dt = _parse_exif_dt(str(raw))
    result["has_exif"] = dt is not None
    result["datetime_original"] = dt
    return result


def _parse_exif_dt(raw: str) -> Optional[datetime]:
    raw = raw.strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(raw, fmt)
        except (ValueError, TypeError):
            continue
    return None


# --- Perceptual hash (near-duplicate detection) -------------------------------------------
def perceptual_hash(path: str) -> Optional[int]:
    """64-bit average hash (8x8 grayscale, mean-threshold). None if unreadable."""
    try:
        small = Image.open(path).convert("L").resize((8, 8), Image.BILINEAR)
    except Exception:
        return None
    pixels = list(small.tobytes())  # mode "L" -> one byte per pixel, row-major
    avg = sum(pixels) / len(pixels)
    bits = 0
    for i, p in enumerate(pixels):
        if p >= avg:
            bits |= (1 << i)
    return bits


def hamming(a: Optional[int], b: Optional[int]) -> int:
    """Hamming distance between two 64-bit hashes; large sentinel if either is missing."""
    if a is None or b is None:
        return 64
    return bin(a ^ b).count("1")
