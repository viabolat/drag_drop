"""image_analysis.py — the deterministic image-lifecycle ordering engine.

Pure functions of the merged signal vector — no image or network access below analyze_and_sequence
(which only orchestrates the provider + CV extraction). The LLM never orders here: it supplies
per-image signals; this module decides bucket, order, confidence, and review routing.

Level 1 (classify_macro_phase): hard gates for live/teardown (the visually-confusable buckets)
then template affinity along the venue->final continuum.
Level 2 (sequence_images): intra-bucket ordering by completeness, with EXIF only as a tie-break /
conflict-flag, then per-position confidence + review flags + a human-readable rationale.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import lifecycle_taxonomy as tax
from analysis_schema import ImageAnalysis, SignalReading
from context_generation import generate_event_context, phase_summary
from image_signals import extract_cv_signals, extract_metadata, perceptual_hash, hamming
from vision_provider import safe_analyze, to_signal_vector


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


# --- internal item -------------------------------------------------------------------------
@dataclass
class _ScoredItem:
    image_path: str
    sv: Dict[str, SignalReading]
    semantic: Dict[str, object]
    meta: Dict[str, object]
    phash: Optional[int]
    original_index: int
    vision_unavailable: bool
    label: str = ""
    state_confidence: float = 0.0
    completeness: float = 0.0
    debug: Dict[str, object] = field(default_factory=dict)
    # filled during sequencing
    bucket: str = ""
    sequence_index: int = 0
    sequence_confidence: float = 0.0
    flags: List[str] = field(default_factory=list)
    metadata_conflict: bool = False
    near_duplicate: bool = False
    used_tiebreak: bool = False


# --- signal merge --------------------------------------------------------------------------
def merge_signals(cv: Dict[str, SignalReading], vision: Dict[str, SignalReading],
                  meta: Dict[str, object]) -> Dict[str, SignalReading]:
    """Union of vision (semantic) + cv (objective) readings. Classification is vision-driven;
    cv signals are surfaced for transparency/tuning and never required (so tests can inject
    vision-only vectors). `meta` travels alongside, not as a SignalReading."""
    merged: Dict[str, SignalReading] = {}
    merged.update(cv or {})
    merged.update(vision or {})
    return merged


# --- Level 1: macro-phase classification ---------------------------------------------------
def _affinity(sv: Dict[str, SignalReading], phase: str) -> float:
    tmpl = tax.PHASE_TEMPLATES[phase]
    weights = tax.SIGNAL_WEIGHTS[phase]
    num = den = 0.0
    for s, expected in tmpl.items():
        r = sv.get(s)
        if r is None:
            continue
        w = weights[s]
        sim = 1.0 - abs(r.value - expected)
        num += w * sim * r.confidence
        den += w * r.confidence
    return num / den if den > 0 else 0.0


def _signal_factor(sv: Dict[str, SignalReading], phase: str) -> float:
    weights = tax.SIGNAL_WEIGHTS[phase]
    num = den = 0.0
    for s, w in weights.items():
        r = sv.get(s)
        if r is None:
            continue
        num += w * r.confidence
        den += w
    return num / den if den > 0 else 0.0


def _gate_confidence(cue_val: float, cue_conf: float, act_hit: bool, act_conf: float,
                     gate: float) -> float:
    vals = []
    if cue_val >= gate and cue_conf >= tax.CONF_MIN:
        span = max(1e-6, 1.0 - gate)
        vals.append(cue_conf * (0.7 + 0.3 * _clamp01((cue_val - gate) / span)))
    if act_hit and act_conf >= tax.CONF_MIN:
        vals.append(act_conf)
    return _clamp01(max(vals)) if vals else 0.0


def classify_macro_phase(sv: Dict[str, SignalReading]) -> Tuple[str, float, Dict[str, object]]:
    """Return (state_label, state_confidence, debug). Gates fire first for live/teardown; the
    continuum winner (cont_winner) is always computed as a placement hint for ambiguous items."""
    # continuum affinities (always computed)
    affinities = {p: _affinity(sv, p) for p in tax.CONTINUUM}
    ordered = sorted(affinities.items(), key=lambda kv: kv[1], reverse=True)
    cont_winner, top = ordered[0]
    runner, second = ordered[1] if len(ordered) > 1 else (cont_winner, top)
    margin = top - second
    debug: Dict[str, object] = {"affinities": affinities, "cont_winner": cont_winner,
                                "runner_up": runner, "margin": margin, "flags": []}

    live = sv.get("live_event_cue", SignalReading(0, 0, "vision"))
    tear = sv.get("teardown_cue", SignalReading(0, 0, "vision"))
    act = sv.get("human_activity_type", SignalReading(0, 0, "vision", raw="none"))
    act_val = act.raw if act.raw is not None else "none"

    live_fires = ((live.value >= tax.LIVE_GATE and live.confidence >= tax.CONF_MIN)
                  or (act_val in ("guests", "audience") and act.confidence >= tax.CONF_MIN))
    teardown_fires = ((tear.value >= tax.TEARDOWN_GATE and tear.confidence >= tax.CONF_MIN)
                      or (act_val == "teardown" and act.confidence >= tax.CONF_MIN))

    if live_fires and teardown_fires:
        debug["flags"].append(tax.FLAG_LIVE_TEARDOWN)
        conf = 0.30 * min(
            _gate_confidence(live.value, live.confidence, act_val in ("guests", "audience"), act.confidence, tax.LIVE_GATE),
            _gate_confidence(tear.value, tear.confidence, act_val == "teardown", act.confidence, tax.TEARDOWN_GATE),
        )
        return tax.AMBIGUOUS, _clamp01(conf), debug
    if live_fires:
        conf = _gate_confidence(live.value, live.confidence, act_val in ("guests", "audience"),
                                act.confidence, tax.LIVE_GATE)
        return "live_event", _clamp01(conf), debug
    if teardown_fires:
        conf = _gate_confidence(tear.value, tear.confidence, act_val == "teardown",
                                act.confidence, tax.TEARDOWN_GATE)
        return "post_event_teardown", _clamp01(conf), debug

    # continuum path
    non_adjacent = abs(tax.MACRO_ORDER[cont_winner] - tax.MACRO_ORDER[runner]) > 1
    margin_factor = 0.5 + 0.5 * _clamp01(margin / tax.MARGIN_FULL)
    sig_factor = _signal_factor(sv, cont_winner)
    state_conf = _clamp01(margin_factor * sig_factor)
    if margin < tax.MARGIN_MIN and non_adjacent:
        debug["flags"].append(tax.FLAG_PHASE_TIE)
        return tax.AMBIGUOUS, _clamp01(state_conf * 0.6), debug
    return cont_winner, state_conf, debug


# --- Level 2: completeness + ordering ------------------------------------------------------
def completeness_score(sv: Dict[str, SignalReading]) -> float:
    num = den = 0.0
    for s, w in tax.COMPLETENESS_WEIGHTS.items():
        r = sv.get(s)
        if r is None:
            continue
        num += w * r.value * r.confidence
        den += w * r.confidence
    return num / den if den > 0 else 0.0


def compute_scale_frac(sequence_index: int, n: int, state_label: str) -> float:
    """Monotonic climbing FADER fill; final/live land near 1.0 by virtue of being last."""
    if n <= 0:
        return 1.0
    return round(max(0.05, min(1.0, (sequence_index + 1) / n)), 4)


def _ts(item: _ScoredItem) -> float:
    dt = item.meta.get("datetime_original")
    return dt.timestamp() if isinstance(dt, datetime) else float("inf")


def _bucket_of(item: _ScoredItem) -> str:
    if item.label == tax.AMBIGUOUS:
        return item.debug.get("cont_winner", "mid_setup")  # best-guess placement, still flagged
    return item.label


def sequence_images(items: List[_ScoredItem], event_context: str = "") -> List[ImageAnalysis]:
    for it in items:
        it.bucket = _bucket_of(it)

    # near-duplicate detection across all pairs (before ordering)
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if hamming(items[i].phash, items[j].phash) <= tax.DUP_HAMMING_THRESH:
                items[i].near_duplicate = True
                items[j].near_duplicate = True

    # order within each bucket
    ordered: List[_ScoredItem] = []
    for bucket in tax.STATE_LABELS:
        group = [it for it in items if it.bucket == bucket]
        if not group:
            continue
        if bucket == "live_event":
            group.sort(key=lambda it: (-it.sv.get("live_event_cue", SignalReading(0, 0, "v")).value,
                                       _ts(it), it.original_index))
        elif bucket == "post_event_teardown":
            group.sort(key=lambda it: (-round(it.completeness / tax.TIE_EPS), _ts(it), it.original_index))
        else:  # venue_only + setup continuum: ascending completeness
            group.sort(key=lambda it: (round(it.completeness / tax.TIE_EPS), _ts(it), it.original_index))
        _annotate_group(group, bucket)
        ordered.extend(group)

    for idx, it in enumerate(ordered):
        it.sequence_index = idx

    _detect_conflicts(ordered)
    _score_sequence(ordered)
    return [_finalize(it, len(ordered), event_context) for it in ordered]


def _annotate_group(group: List[_ScoredItem], bucket: str) -> None:
    """Mark items whose EXIF was consulted to break a visual (near-equal completeness) tie
    within a completeness-ordered bucket. Skipped for live_event (not completeness-ordered)."""
    if bucket == "live_event":
        return
    for a in group:
        for b in group:
            if a is b:
                continue
            if abs(a.completeness - b.completeness) < tax.TIE_EPS and a.meta.get("has_exif"):
                a.used_tiebreak = True


def _detect_conflicts(ordered: List[_ScoredItem]) -> None:
    """Flag EXIF-vs-visual disagreement across the completeness-ordered region (venue_only +
    setup continuum). Adjacent pair a-before-b: a is visually earlier; if both carry EXIF and a
    was captured clearly AFTER b, that's a conflict. Visual order is NEVER changed — only
    sequence_confidence drops and the pair is routed to review (metadata is strictly secondary)."""
    region = set(tax.CONTINUUM)
    for k in range(len(ordered) - 1):
        a, b = ordered[k], ordered[k + 1]
        if a.bucket not in region or b.bucket not in region:
            continue
        if not (a.meta.get("has_exif") and b.meta.get("has_exif")):
            continue
        clear_visual = (a.bucket != b.bucket) or (abs(a.completeness - b.completeness) > tax.TIE_EPS)
        if clear_visual and _ts(a) > _ts(b) + tax.METADATA_CONFLICT_TOL_S:
            a.metadata_conflict = True
            b.metadata_conflict = True


def _score_sequence(ordered: List[_ScoredItem]) -> None:
    # group neighbor gaps computed within the same bucket
    by_bucket: Dict[str, List[_ScoredItem]] = {}
    for it in ordered:
        by_bucket.setdefault(it.bucket, []).append(it)
    for group in by_bucket.values():
        for pos, it in enumerate(group):
            gaps = []
            if pos > 0:
                gaps.append(abs(it.completeness - group[pos - 1].completeness))
            if pos < len(group) - 1:
                gaps.append(abs(it.completeness - group[pos + 1].completeness))
            neighbor_gap = min(gaps) if gaps else 1.0
            gap_factor = _clamp01(neighbor_gap / tax.GAP_FULL)
            base = 0.5 * it.state_confidence + 0.5 * gap_factor
            if it.metadata_conflict:
                meta_factor = -tax.META_PENALTY
            elif it.meta.get("has_exif"):
                meta_factor = tax.META_BONUS
            else:
                meta_factor = 0.0
            dup_pen = tax.DUP_PENALTY if it.near_duplicate else 0.0
            it.sequence_confidence = _clamp01(base + meta_factor - dup_pen)


def _finalize(it: _ScoredItem, n: int, event_context: str) -> ImageAnalysis:
    alt = str(it.semantic.get("alt_description", ""))
    flags = list(it.debug.get("flags", []))
    if it.vision_unavailable:
        flags.append(tax.FLAG_VISION_UNAVAILABLE)
    if it.state_confidence < tax.STATE_REVIEW_THRESH:
        flags.append(tax.FLAG_LOW_STATE)
    if it.sequence_confidence < tax.SEQ_REVIEW_THRESH:
        flags.append(tax.FLAG_LOW_SEQ)
    if it.metadata_conflict:
        flags.append(tax.FLAG_META_CONFLICT)
    if it.near_duplicate:
        flags.append(tax.FLAG_NEAR_DUP)
    if not it.meta.get("has_exif"):
        flags.append(tax.FLAG_NO_META)
    flags = sorted(set(flags))

    review = bool(
        it.vision_unavailable
        or it.label == tax.AMBIGUOUS
        or it.state_confidence < tax.STATE_REVIEW_THRESH
        or it.sequence_confidence < tax.SEQ_REVIEW_THRESH
        or it.metadata_conflict
        or it.near_duplicate
        or tax.FLAG_PHASE_TIE in flags
        or tax.FLAG_LIVE_TEARDOWN in flags
    )

    event_ctx, ctx_conf = generate_event_context(
        it.label, alt, event_context, it.state_confidence)

    signals_detected = {}
    for name, r in it.sv.items():
        entry = {"value": round(r.value, 4), "confidence": round(r.confidence, 4), "source": r.source}
        if r.raw is not None:
            entry["category"] = r.raw
        signals_detected[name] = entry

    dt = it.meta.get("datetime_original")
    metadata_used = {
        "has_exif": bool(it.meta.get("has_exif")),
        "datetime_original": dt.isoformat() if isinstance(dt, datetime) else None,
        "used_as_tiebreak": it.used_tiebreak,
        "conflict": it.metadata_conflict,
    }

    return ImageAnalysis(
        image_path=it.image_path,
        state_label=it.label,
        state_confidence=it.state_confidence,
        sequence_index=it.sequence_index,
        sequence_confidence=it.sequence_confidence,
        ordering_rationale=_rationale(it, n),
        event_context=event_ctx,
        context_confidence=ctx_conf,
        alt_description=alt,
        phase_summary=phase_summary(it.label),
        signals_detected=signals_detected,
        metadata_used=metadata_used,
        ambiguity_flags=flags,
        review_required=review,
    )


def _rationale(it: _ScoredItem, n: int) -> str:
    parts = [f"Placed {it.sequence_index + 1} of {n} in {it.label} "
             f"(completeness {it.completeness:.2f}, state confidence {it.state_confidence:.2f})."]
    if it.label == tax.AMBIGUOUS:
        parts.append(f"Ambiguous — best-guess bucket {it.bucket}; flagged for review.")
    if it.metadata_conflict:
        parts.append("EXIF capture time contradicts the visual order; visual order kept, confidence lowered.")
    elif it.meta.get("has_exif"):
        parts.append("EXIF capture time consistent with visual order.")
    else:
        parts.append("No EXIF capture time; ordered on visual evidence alone.")
    if it.near_duplicate:
        parts.append("Near-duplicate of another image; flagged for review.")
    parts.append(f"Sequence confidence {it.sequence_confidence:.2f}.")
    return " ".join(parts)


# --- orchestration -------------------------------------------------------------------------
def analyze_and_sequence(image_paths: List[str], event_context: str, analyzer) -> List[ImageAnalysis]:
    """End-to-end: per image -> vision signals + CV + EXIF + phash -> merge -> classify ->
    completeness; then deterministic sequencing. `analyzer` is any VisionAnalyzer."""
    items: List[_ScoredItem] = []
    for idx, path in enumerate(image_paths):
        semantic, unavailable = safe_analyze(analyzer, path, event_context)
        vision_sv = to_signal_vector(semantic)
        cv = extract_cv_signals(path)
        meta = extract_metadata(path)
        phash = perceptual_hash(path)
        sv = merge_signals(cv, vision_sv, meta)
        label, sconf, debug = classify_macro_phase(sv)
        if unavailable:
            # Don't let a zero-signal (failed) vision call masquerade as a confident
            # "venue_only"; label it ambiguous so the operator sees it's unclassified.
            label = tax.AMBIGUOUS
        comp = completeness_score(sv)
        items.append(_ScoredItem(
            image_path=path, sv=sv, semantic=semantic, meta=meta, phash=phash,
            original_index=idx, vision_unavailable=unavailable,
            label=label, state_confidence=sconf, completeness=comp, debug=debug))
    return sequence_images(items, event_context)
