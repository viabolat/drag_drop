"""lifecycle_taxonomy.py — the single source of truth for the image-lifecycle layer.

Constants only, no logic (mirrors how compositor.py keeps its brand/canvas constants at the
top of the file). Everything tunable lives here so the deterministic engine (image_analysis.py)
and the tests import the SAME numbers — a weight change can never silently desync from a test.

Design rules encoded here (see the plan):
  - Ordering is a pure function of visual signals; filenames are NEVER a signal.
  - Metadata (EXIF) is strictly secondary: tie-break / conflict-flag only.
  - The LLM emits per-image signals only; sequencing is decided here, never by the LLM.
"""

# --- Canonical macro-phases (index == ordering rank) --------------------------------------
STATE_LABELS = (
    "venue_only",            # empty/undressed room, no AV, no people
    "pre_setup",             # gear staged but not installed (cases, coiled cable, ladders)
    "early_setup",           # rigging/trussing going up, structure only
    "mid_setup",             # AV installed, cabling/decor in progress
    "late_setup",            # near-complete, final dress/cable-management, crew only
    "final_ready",           # complete, polished, lit, no audience yet
    "live_event",            # audience/guests present, show active (own bucket, not "max completeness")
    "post_event_teardown",   # striking gear: partial rig, stacked cases, debris
)
AMBIGUOUS = "ambiguous_mixed"   # sentinel; never a normal ordering slot

MACRO_ORDER = {label: i for i, label in enumerate(STATE_LABELS)}
SETUP_CONTINUUM = STATE_LABELS[1:6]          # pre_setup .. final_ready (continuously orderable)
CONTINUUM = STATE_LABELS[0:6]                # venue_only .. final_ready (template-classified)

# Advisory sublabels — shown in review, do NOT affect ordering.
SUBLABELS = {
    "mid_setup": ("cabling", "led_wall_raise", "lighting_focus", "audio_ring_out"),
    "live_event": ("doors_open", "peak", "keynote", "performance"),
    "post_event_teardown": ("strike_start", "load_out"),
}

# --- Signal names -------------------------------------------------------------------------
# Semantic signals — supplied by the vision model (analyze_image.mjs).
VISION_NUMERIC = (
    "venue_readiness",
    "av_staging_completeness",
    "decor_completeness",
    "polish_vs_clutter",
    "live_event_cue",
    "teardown_cue",
)
ACTIVITY_VALUES = ("none", "crew", "guests", "audience", "teardown")
# Objective signals — supplied by image_signals.py (numpy/Pillow); assistive only.
CV_SIGNALS = ("brightness_mean", "sharpness_var", "edge_density", "colorfulness")

# --- Phase templates & weights (Level-1 classification) -----------------------------------
# Expected value per readiness signal for each continuum phase.
PHASE_TEMPLATES = {
    "venue_only":  {"venue_readiness": 0.05, "av_staging_completeness": 0.02, "decor_completeness": 0.02, "polish_vs_clutter": 0.60},
    "pre_setup":   {"venue_readiness": 0.15, "av_staging_completeness": 0.10, "decor_completeness": 0.05, "polish_vs_clutter": 0.20},
    "early_setup": {"venue_readiness": 0.30, "av_staging_completeness": 0.30, "decor_completeness": 0.15, "polish_vs_clutter": 0.25},
    "mid_setup":   {"venue_readiness": 0.55, "av_staging_completeness": 0.60, "decor_completeness": 0.45, "polish_vs_clutter": 0.40},
    "late_setup":  {"venue_readiness": 0.80, "av_staging_completeness": 0.85, "decor_completeness": 0.75, "polish_vs_clutter": 0.70},
    "final_ready": {"venue_readiness": 0.95, "av_staging_completeness": 0.95, "decor_completeness": 0.92, "polish_vs_clutter": 0.95},
}
# Per-signal importance when scoring affinity to each phase.
SIGNAL_WEIGHTS = {
    "venue_only":  {"venue_readiness": 1.0, "av_staging_completeness": 1.5, "decor_completeness": 1.5, "polish_vs_clutter": 0.5},
    "pre_setup":   {"venue_readiness": 1.0, "av_staging_completeness": 1.0, "decor_completeness": 0.5, "polish_vs_clutter": 1.5},
    "early_setup": {"venue_readiness": 1.0, "av_staging_completeness": 1.5, "decor_completeness": 0.8, "polish_vs_clutter": 1.0},
    "mid_setup":   {"venue_readiness": 1.0, "av_staging_completeness": 1.5, "decor_completeness": 1.0, "polish_vs_clutter": 1.0},
    "late_setup":  {"venue_readiness": 1.2, "av_staging_completeness": 1.2, "decor_completeness": 1.2, "polish_vs_clutter": 1.2},
    "final_ready": {"venue_readiness": 1.2, "av_staging_completeness": 1.2, "decor_completeness": 1.2, "polish_vs_clutter": 1.5},
}
# Weights for the intra-bucket completeness composite (Level-2 ordering).
COMPLETENESS_WEIGHTS = {
    "venue_readiness": 1.0,
    "av_staging_completeness": 1.2,
    "decor_completeness": 1.0,
    "polish_vs_clutter": 0.8,
}

# --- Thresholds / calibration -------------------------------------------------------------
LIVE_GATE = 0.5             # live_event_cue value at/above which the live gate can fire
TEARDOWN_GATE = 0.5         # teardown_cue value at/above which the teardown gate can fire
CONF_MIN = 0.4             # min confidence for a gate/categorical to be trusted
MARGIN_MIN = 0.06          # affinity margin below which non-adjacent top-2 => ambiguous
MARGIN_FULL = 0.25         # margin at which the margin confidence factor saturates
TIE_EPS = 0.05             # completeness within this counts as a visual tie
GAP_FULL = 0.20            # neighbor completeness gap that saturates the gap factor
META_BONUS = 0.10          # sequence_confidence bonus when EXIF agrees with visual order
META_PENALTY = 0.20        # penalty when EXIF clearly contradicts a clear visual order
DUP_PENALTY = 0.25         # sequence_confidence penalty for a near-duplicate
DUP_HAMMING_THRESH = 8     # aHash Hamming distance at/below which two images are near-dupes
METADATA_CONFLICT_TOL_S = 120   # EXIF disagreement tolerance, seconds
STATE_REVIEW_THRESH = 0.45      # state_confidence below this => review_required
SEQ_REVIEW_THRESH = 0.40        # sequence_confidence below this => review_required

# CV normalization references (map a raw measurement to ~1.0). Used only by image_signals.py.
SHARPNESS_VAR_REF = 1500.0
EDGE_DENSITY_REF = 40.0
COLORFULNESS_REF = 80.0
CV_CONFIDENCE = 0.5             # baseline confidence for numpy CV signals
CV_CONFIDENCE_FALLBACK = 0.35   # lower confidence when numpy is unavailable (Pillow-only path)

# --- Controlled vocabulary for ambiguity_flags --------------------------------------------
FLAG_LOW_STATE = "low_state_confidence"
FLAG_LOW_SEQ = "low_sequence_confidence"
FLAG_PHASE_TIE = "phase_tie_nonadjacent"
FLAG_LIVE_TEARDOWN = "live_teardown_ambiguous"
FLAG_META_CONFLICT = "metadata_conflict"
FLAG_NO_META = "no_metadata"
FLAG_NEAR_DUP = "near_duplicate"
FLAG_VISION_UNAVAILABLE = "vision_unavailable"
