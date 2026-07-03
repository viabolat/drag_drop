"""analysis_schema.py — dataclasses for the image-lifecycle layer.

`SignalReading` is the atom of the signal vector; `ImageAnalysis` is the per-image output
contract consumed by the /analyze-sequence/ endpoint and the review UI. Kept free of engine
logic so tests can construct/round-trip these directly.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class SignalReading:
    """One signal: a normalized value + confidence + provenance.

    value: 0..1 for numeric signals; for categoricals the category string lives in `raw` and
           `value` carries a numeric proxy (or 0.0 when not applicable).
    source: "vision" | "cv" | "metadata" | "blend".
    """
    value: float
    confidence: float
    source: str
    raw: Any = None

    def as_dict(self) -> Dict[str, Any]:
        d = {"value": self.value, "confidence": self.confidence, "source": self.source}
        if self.raw is not None:
            d["raw"] = self.raw if not isinstance(self.raw, datetime) else self.raw.isoformat()
        return d


# The exact per-image output keys required by the spec.
@dataclass
class ImageAnalysis:
    image_path: str
    state_label: str
    state_confidence: float
    sequence_index: int
    sequence_confidence: float
    ordering_rationale: str
    event_context: str
    context_confidence: float
    alt_description: str
    phase_summary: str
    signals_detected: Dict[str, Any] = field(default_factory=dict)
    metadata_used: Dict[str, Any] = field(default_factory=dict)
    ambiguity_flags: List[str] = field(default_factory=list)
    review_required: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "image_path": self.image_path,
            "state_label": self.state_label,
            "state_confidence": round(self.state_confidence, 4),
            "sequence_index": self.sequence_index,
            "sequence_confidence": round(self.sequence_confidence, 4),
            "ordering_rationale": self.ordering_rationale,
            "event_context": self.event_context,
            "context_confidence": round(self.context_confidence, 4),
            "alt_description": self.alt_description,
            "phase_summary": self.phase_summary,
            "signals_detected": _json_safe(self.signals_detected),
            "metadata_used": _json_safe(self.metadata_used),
            "ambiguity_flags": list(self.ambiguity_flags),
            "review_required": self.review_required,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ImageAnalysis":
        return cls(
            image_path=d["image_path"],
            state_label=d["state_label"],
            state_confidence=float(d.get("state_confidence", 0.0)),
            sequence_index=int(d.get("sequence_index", 0)),
            sequence_confidence=float(d.get("sequence_confidence", 0.0)),
            ordering_rationale=d.get("ordering_rationale", ""),
            event_context=d.get("event_context", ""),
            context_confidence=float(d.get("context_confidence", 0.0)),
            alt_description=d.get("alt_description", ""),
            phase_summary=d.get("phase_summary", ""),
            signals_detected=d.get("signals_detected", {}),
            metadata_used=d.get("metadata_used", {}),
            ambiguity_flags=list(d.get("ambiguity_flags", [])),
            review_required=bool(d.get("review_required", False)),
        )


def _json_safe(obj: Any) -> Any:
    """Recursively coerce datetimes to ISO strings so the dict is JSON-serializable."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj
