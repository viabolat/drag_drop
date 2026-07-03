"""vision_provider.py — the pluggable LLM seam for per-image visual signals.

The vision model emits SEMANTIC SIGNALS ONLY — there is deliberately no order/index field, so
the LLM is structurally incapable of choosing the sequence (deterministic Python owns that).

Implementations:
  - ClaudeVisionAnalyzer: real. Python downscales the image to a bounded JPEG, then shells to
    analyze_image.mjs (Claude Agent SDK, subscription token). Never raises.
  - DictVisionAnalyzer: tests inject canned semantic dicts keyed by image path.
  - safe_analyze(): enforces the never-raise contract and reports vision_unavailable.

This mirrors text_generation.py's subprocess boundary + mock-fallback exactly, so the suite
mocks vision the same way it already mocks slide-copy generation.
"""
import os
import json
import random
import subprocess
import tempfile
import time
from typing import Dict, Optional, Protocol, Tuple

from PIL import Image

import lifecycle_taxonomy as tax
from analysis_schema import SignalReading

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
NODE_SCRIPT_PATH = os.path.join(_MODULE_DIR, "analyze_image.mjs")
SUBPROCESS_TIMEOUT_SECONDS = 90
MAX_EDGE_PX = 1536          # bound the long edge so base64 stays under vision size limits
JPEG_QUALITY = 85
# Bounded retry policy for opaque fast-fail subprocess errors: a hard cap on attempts +
# exponential backoff with full jitter. Retries are strictly sequential (in-line loop) — never
# parallel — so they cannot amplify load on the subprocess.
RETRY_ATTEMPTS = 3                  # hard cap on total attempts (<= 2 retries)
RETRY_BASE_BACKOFF_SECONDS = 0.5    # exponential base
RETRY_MAX_BACKOFF_SECONDS = 4.0     # backoff ceiling


def _backoff_delay(attempt: int) -> float:
    """Full-jitter exponential backoff: uniform(0, min(cap, base * 2**attempt))."""
    capped = min(RETRY_MAX_BACKOFF_SECONDS, RETRY_BASE_BACKOFF_SECONDS * (2 ** attempt))
    return random.uniform(0.0, capped)

# Neutral semantic vector — all confidence 0.0. Returned on any failure so the engine collapses
# state_confidence to ~0 and routes the item to human review, instead of trusting a fabrication.
MOCK_SEMANTIC: Dict[str, object] = {
    **{s: {"value": 0.0, "confidence": 0.0} for s in tax.VISION_NUMERIC},
    "human_activity_type": {"value": "none", "confidence": 0.0},
    "alt_description": "[MOCK] vision unavailable",
    "raw_labels": ["[MOCK]"],
}


class VisionAnalyzer(Protocol):
    def analyze(self, image_path: str, event_context: str = "") -> Dict[str, object]:
        """Return a semantic signal dict for ONE image (no ordering field). Must not raise."""
        ...


def _bounded_jpeg(src: str) -> Optional[str]:
    """Downscale src to a bounded temp JPEG; return its path (caller deletes) or None on error."""
    try:
        im = Image.open(src)
        im.load()
        im = im.convert("RGB")
        im.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX))
        fd, out = tempfile.mkstemp(suffix=".jpg", prefix="__vision_")
        os.close(fd)
        im.save(out, "JPEG", quality=JPEG_QUALITY)
        return out
    except Exception:
        return None


class ClaudeVisionAnalyzer:
    """Real analyzer: bounded-JPEG downscale (Python) -> analyze_image.mjs (Node, subscription)."""

    def analyze(self, image_path: str, event_context: str = "") -> Dict[str, object]:
        bounded = _bounded_jpeg(image_path)
        if bounded is None:
            return dict(MOCK_SEMANTIC)
        try:
            # Bounded, sequential retries (exponential backoff + jitter) to absorb opaque
            # fast-fail subprocess errors. A nonzero exit / malformed JSON is retried; a missing
            # node binary or a full timeout is not (retrying won't fix the former and is too
            # costly for the latter). An image that fails deterministically simply exhausts the
            # attempts and falls to MOCK -> human review, per the agreed never-raise contract.
            for attempt in range(RETRY_ATTEMPTS):
                try:
                    proc = subprocess.run(
                        ["node", NODE_SCRIPT_PATH, event_context or "", bounded],
                        capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SECONDS,
                        cwd=_MODULE_DIR,
                    )
                except FileNotFoundError:
                    return dict(MOCK_SEMANTIC)          # node not installed
                except subprocess.TimeoutExpired:
                    return dict(MOCK_SEMANTIC)          # too expensive to retry
                if proc.returncode == 0:
                    try:
                        return _validate_semantic(json.loads(proc.stdout))
                    except Exception:
                        pass                            # malformed output -> retry
                if attempt < RETRY_ATTEMPTS - 1:
                    time.sleep(_backoff_delay(attempt))
            return dict(MOCK_SEMANTIC)
        finally:
            try:
                os.remove(bounded)
            except OSError:
                pass


class DictVisionAnalyzer:
    """Test analyzer: returns canned semantic dicts keyed by image path (default MOCK)."""

    def __init__(self, mapping: Dict[str, Dict[str, object]]):
        self.mapping = mapping

    def analyze(self, image_path: str, event_context: str = "") -> Dict[str, object]:
        return dict(self.mapping.get(image_path, MOCK_SEMANTIC))


def _validate_semantic(parsed: object) -> Dict[str, object]:
    """Shape-check the mjs output; fall back to MOCK on any deviation (never raise upward)."""
    if not isinstance(parsed, dict):
        return dict(MOCK_SEMANTIC)
    out: Dict[str, object] = {}
    for s in tax.VISION_NUMERIC:
        r = parsed.get(s)
        if not isinstance(r, dict) or "value" not in r or "confidence" not in r:
            return dict(MOCK_SEMANTIC)
        out[s] = {"value": _clamp01(r["value"]), "confidence": _clamp01(r["confidence"])}
    act = parsed.get("human_activity_type")
    if not isinstance(act, dict) or act.get("value") not in tax.ACTIVITY_VALUES:
        return dict(MOCK_SEMANTIC)
    out["human_activity_type"] = {"value": act["value"], "confidence": _clamp01(act.get("confidence", 0.0))}
    out["alt_description"] = str(parsed.get("alt_description", ""))
    labels = parsed.get("raw_labels", [])
    out["raw_labels"] = [str(x) for x in labels][:12] if isinstance(labels, list) else []
    return out


def _clamp01(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


def _is_mock(semantic: Dict[str, object]) -> bool:
    """A semantic vector with zero confidence everywhere is treated as unavailable."""
    for s in tax.VISION_NUMERIC:
        if float(semantic.get(s, {}).get("confidence", 0.0)) > 0.0:
            return False
    return float(semantic.get("human_activity_type", {}).get("confidence", 0.0)) == 0.0


def safe_analyze(analyzer: VisionAnalyzer, image_path: str,
                 event_context: str = "") -> Tuple[Dict[str, object], bool]:
    """Run the analyzer under the never-raise contract.

    Returns (semantic_dict, vision_unavailable). vision_unavailable is True if the analyzer
    raised or returned a mock/all-zero-confidence vector.
    """
    try:
        semantic = analyzer.analyze(image_path, event_context)
    except Exception:
        return dict(MOCK_SEMANTIC), True
    if not isinstance(semantic, dict):
        return dict(MOCK_SEMANTIC), True
    return semantic, _is_mock(semantic)


def to_signal_vector(semantic: Dict[str, object]) -> Dict[str, SignalReading]:
    """Map a raw semantic dict to vision-sourced SignalReadings (categorical in `raw`)."""
    sv: Dict[str, SignalReading] = {}
    for s in tax.VISION_NUMERIC:
        r = semantic.get(s, {"value": 0.0, "confidence": 0.0})
        sv[s] = SignalReading(_clamp01(r.get("value", 0.0)), _clamp01(r.get("confidence", 0.0)), "vision")
    act = semantic.get("human_activity_type", {"value": "none", "confidence": 0.0})
    sv["human_activity_type"] = SignalReading(
        0.0, _clamp01(act.get("confidence", 0.0)), "vision", raw=act.get("value", "none"))
    return sv
