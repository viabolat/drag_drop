"""Deterministic engine tests — signal vectors injected via DictVisionAnalyzer, no LLM, no
real images for the pure-ordering cases (CV/EXIF on nonexistent paths return neutral)."""
import pytest

import lifecycle_taxonomy as tax
from analysis_schema import ImageAnalysis
from image_analysis import (
    analyze_and_sequence, classify_macro_phase, completeness_score, compute_scale_frac,
)
from vision_provider import DictVisionAnalyzer, to_signal_vector

pytestmark = pytest.mark.unit


def _by_path(results):
    return {r.image_path: r for r in results}


def _vec(make_signals, **kw):
    return to_signal_vector(make_signals(**kw))


# --- classification --------------------------------------------------------------------------
PHASE_CASES = {
    "venue_only": dict(vr=0.05, av=0.02, dec=0.02, pol=0.70),
    "pre_setup": dict(vr=0.15, av=0.10, dec=0.05, pol=0.20, activity="crew"),
    "early_setup": dict(vr=0.30, av=0.30, dec=0.15, pol=0.25, activity="crew"),
    "mid_setup": dict(vr=0.55, av=0.60, dec=0.45, pol=0.40, activity="crew"),
    "late_setup": dict(vr=0.80, av=0.85, dec=0.75, pol=0.70, activity="crew"),
    "final_ready": dict(vr=0.95, av=0.95, dec=0.92, pol=0.95),
    "live_event": dict(vr=0.9, av=0.9, dec=0.9, pol=0.3, live=0.9, activity="audience"),
    "post_event_teardown": dict(vr=0.4, av=0.5, dec=0.3, pol=0.2, tear=0.8, activity="teardown"),
}


@pytest.mark.parametrize("expected,kw", list(PHASE_CASES.items()))
def test_phase_regression_each_vector_classifies_to_its_own_label(make_signals, expected, kw):
    label, conf, _ = classify_macro_phase(_vec(make_signals, **kw))
    assert label == expected, f"{expected} vector classified as {label}"
    assert conf > tax.STATE_REVIEW_THRESH


def test_completeness_is_monotonic_across_setup_band(make_signals):
    scores = [completeness_score(_vec(make_signals, **PHASE_CASES[p])) for p in tax.SETUP_CONTINUUM]
    assert scores == sorted(scores), scores


# --- ordering --------------------------------------------------------------------------------
def test_canonical_order_from_shuffled_input(make_signals):
    mapping = {f"p_{name}": make_signals(**kw) for name, kw in PHASE_CASES.items()}
    shuffled = ["p_live_event", "p_venue_only", "p_final_ready", "p_pre_setup",
                "p_post_event_teardown", "p_mid_setup", "p_early_setup", "p_late_setup"]
    results = analyze_and_sequence(shuffled, "", DictVisionAnalyzer(mapping))
    order = [r.image_path for r in sorted(results, key=lambda r: r.sequence_index)]
    assert order == [f"p_{n}" for n in tax.STATE_LABELS]


def test_right_context_attaches_to_right_image_after_scramble(make_signals):
    # Each image gets a UNIQUE alt_description; after reordering, each result's context must
    # still carry its own image's alt (guards the index-alignment class of bug).
    mapping = {f"p_{name}": make_signals(alt=f"ALT::{name}", **kw)
               for name, kw in PHASE_CASES.items()}
    shuffled = list(reversed(list(mapping)))
    results = _by_path(analyze_and_sequence(shuffled, "gala", DictVisionAnalyzer(mapping)))
    for name in PHASE_CASES:
        r = results[f"p_{name}"]
        assert r.alt_description == f"ALT::{name}"
        assert f"ALT::{name}" in r.event_context


def test_determinism_same_input_same_output(make_signals):
    mapping = {f"p_{n}": make_signals(**kw) for n, kw in PHASE_CASES.items()}
    paths = list(mapping)
    a = analyze_and_sequence(paths, "", DictVisionAnalyzer(mapping))
    b = analyze_and_sequence(paths, "", DictVisionAnalyzer(mapping))
    assert [(r.image_path, r.sequence_index, r.state_label) for r in a] == \
           [(r.image_path, r.sequence_index, r.state_label) for r in b]


# --- gates: live vs teardown must not collapse to "max completeness" -------------------------
def test_live_and_teardown_are_separate_buckets_not_both_final(make_signals):
    mapping = {
        "p_live": make_signals(vr=0.85, av=0.85, dec=0.8, pol=0.4, live=0.9, activity="audience"),
        "p_tear": make_signals(vr=0.85, av=0.85, dec=0.8, pol=0.3, tear=0.9, activity="teardown"),
        "p_final": make_signals(**PHASE_CASES["final_ready"]),
    }
    res = _by_path(analyze_and_sequence(list(mapping), "", DictVisionAnalyzer(mapping)))
    assert res["p_live"].state_label == "live_event"
    assert res["p_tear"].state_label == "post_event_teardown"
    assert res["p_final"].state_label == "final_ready"
    # canonical lifecycle order: final_ready < live_event < post_event_teardown
    assert res["p_final"].sequence_index < res["p_live"].sequence_index < res["p_tear"].sequence_index


def test_both_gates_firing_is_ambiguous_and_flagged(make_signals):
    mapping = {"p": make_signals(live=0.9, tear=0.9, activity="audience")}
    r = analyze_and_sequence(["p"], "", DictVisionAnalyzer(mapping))[0]
    assert r.state_label == tax.AMBIGUOUS
    assert r.review_required
    assert tax.FLAG_LIVE_TEARDOWN in r.ambiguity_flags


# --- confidence / review routing -------------------------------------------------------------
def test_low_confidence_signals_trigger_review(make_signals):
    mapping = {"p": make_signals(vr=0.5, av=0.5, dec=0.5, pol=0.5, conf=0.1)}
    r = analyze_and_sequence(["p"], "", DictVisionAnalyzer(mapping))[0]
    assert r.state_confidence < tax.STATE_REVIEW_THRESH
    assert r.review_required
    assert tax.FLAG_LOW_STATE in r.ambiguity_flags


def test_mock_vision_marks_unavailable_and_reviews():
    # empty mapping -> DictVisionAnalyzer returns MOCK_SEMANTIC (all confidence 0)
    r = analyze_and_sequence(["p_missing"], "", DictVisionAnalyzer({}))[0]
    assert r.review_required
    assert tax.FLAG_VISION_UNAVAILABLE in r.ambiguity_flags
    assert r.state_confidence < tax.STATE_REVIEW_THRESH
    # honest labeling: a failed vision call is ambiguous, not a fabricated "venue_only"
    assert r.state_label == tax.AMBIGUOUS


def test_adjacent_states_order_deterministically(make_signals):
    mapping = {
        "p_mid": make_signals(**PHASE_CASES["mid_setup"]),
        "p_late": make_signals(**PHASE_CASES["late_setup"]),
    }
    res = _by_path(analyze_and_sequence(list(mapping), "", DictVisionAnalyzer(mapping)))
    assert res["p_mid"].sequence_index < res["p_late"].sequence_index
    assert res["p_mid"].state_label in tax.SETUP_CONTINUUM
    assert res["p_late"].state_label in tax.SETUP_CONTINUUM


# --- EXIF: tie-break + conflict (needs real files with embedded EXIF) ------------------------
def test_exif_breaks_a_visual_tie(make_signals, make_phase_jpeg):
    # identical vision signals => visual tie; earlier EXIF capture time sorts first
    p_late = make_phase_jpeg("late", exif_dt="2024:06:01 20:00:00")
    p_early = make_phase_jpeg("early", exif_dt="2024:06:01 18:00:00")
    sig = make_signals(**PHASE_CASES["mid_setup"])
    mapping = {p_late: sig, p_early: sig}
    res = _by_path(analyze_and_sequence([p_late, p_early], "", DictVisionAnalyzer(mapping)))
    assert res[p_early].sequence_index < res[p_late].sequence_index
    assert res[p_early].metadata_used["has_exif"] is True


def test_exif_conflict_is_flagged_but_does_not_reorder(make_signals, make_phase_jpeg):
    # clear visual order (A less complete than B) but EXIF says A captured AFTER B
    p_a = make_phase_jpeg("a", exif_dt="2024:06:01 21:00:00")  # earlier phase, later EXIF
    p_b = make_phase_jpeg("b", exif_dt="2024:06:01 19:00:00")  # later phase, earlier EXIF
    mapping = {
        p_a: make_signals(**PHASE_CASES["early_setup"]),
        p_b: make_signals(**PHASE_CASES["late_setup"]),
    }
    res = _by_path(analyze_and_sequence([p_a, p_b], "", DictVisionAnalyzer(mapping)))
    # visual order preserved: early_setup before late_setup
    assert res[p_a].sequence_index < res[p_b].sequence_index
    assert res[p_a].metadata_used["conflict"] and res[p_b].metadata_used["conflict"]
    assert res[p_a].review_required and res[p_b].review_required


# --- schema ----------------------------------------------------------------------------------
def test_output_has_all_required_keys(make_signals):
    r = analyze_and_sequence(["p"], "", DictVisionAnalyzer({"p": make_signals()}))[0]
    d = r.to_dict()
    for key in ("image_path", "state_label", "state_confidence", "sequence_index",
                "sequence_confidence", "ordering_rationale", "event_context",
                "context_confidence", "alt_description", "phase_summary",
                "signals_detected", "metadata_used", "ambiguity_flags", "review_required"):
        assert key in d


def test_imageanalysis_dict_roundtrip():
    a = ImageAnalysis(
        image_path="x", state_label="mid_setup", state_confidence=0.7, sequence_index=2,
        sequence_confidence=0.6, ordering_rationale="r", event_context="c",
        context_confidence=0.5, alt_description="alt", phase_summary="s",
        signals_detected={"venue_readiness": {"value": 0.5, "confidence": 0.9, "source": "vision"}},
        metadata_used={"has_exif": False}, ambiguity_flags=["no_metadata"], review_required=True)
    b = ImageAnalysis.from_dict(a.to_dict())
    assert b.to_dict() == a.to_dict()


def test_compute_scale_frac_climbs_monotonically():
    n = 5
    fracs = [compute_scale_frac(i, n, "mid_setup") for i in range(n)]
    assert fracs == sorted(fracs)
    assert fracs[-1] == 1.0
