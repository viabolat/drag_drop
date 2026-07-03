"""context_generation.py — grounded per-image Event Context (no LLM in this step).

`generate_event_context` builds the per-image "Event Context (for AI-generated slide copy)"
string from the DETECTED state + the image's own alt_description + the operator's global event
context. Because it is templated from signals the engine already trusts, the context can never
drift away from what the image actually shows — this is the correctness guarantee behind
"assign the correct context to the correct image".

Copy refinement (turning each grounded context into {kicker,headline,sub} via the existing
generate_slide_copy.mjs) is wired at the endpoint layer (Phase 4), not here.
"""
from typing import List, Tuple

import lifecycle_taxonomy as tax
from text_generation import generate_slide_copy

# One phrase per macro-phase describing that image's true role in the event lifecycle.
_PHASE_PHRASE = {
    "venue_only": "an empty venue establishing shot before any setup",
    "pre_setup": "a pre-setup / load-in scene, gear staged but not yet installed",
    "early_setup": "an early-setup scene, structure and rigging going up",
    "mid_setup": "a mid-setup scene, AV installed and dressing in progress",
    "late_setup": "a late-setup scene, near-complete with final dressing underway",
    "final_ready": "the finished, fully-staged, guest-ready room before doors",
    "live_event": "the live event in progress",
    "post_event_teardown": "the post-event teardown / strike",
    tax.AMBIGUOUS: "an ambiguous / mixed-state moment",
}

_PHASE_SUMMARY = {
    "venue_only": "Venue-only — empty establishing shot",
    "pre_setup": "Pre-setup — gear staged, load-in",
    "early_setup": "Early setup — rigging going up",
    "mid_setup": "Mid setup — AV in, dressing underway",
    "late_setup": "Late setup — near-complete, final dress",
    "final_ready": "Final-ready — fully staged, guest-ready",
    "live_event": "Live event — show in progress",
    "post_event_teardown": "Teardown — strike / load-out",
    tax.AMBIGUOUS: "Ambiguous / mixed-state",
}


def phase_summary(state_label: str) -> str:
    return _PHASE_SUMMARY.get(state_label, state_label)


def generate_event_context(state_label: str, alt_description: str, event_context: str,
                           state_confidence: float) -> Tuple[str, float]:
    """Return (grounded_context, context_confidence).

    The string names the image's true lifecycle role, appends the operator's global event
    context (if any), and grounds the whole thing in the image's own alt_description.
    context_confidence tracks how sure we are of the state (a wrong state => wrong context).
    """
    phrase = _PHASE_PHRASE.get(state_label, "an event image")
    parts = [f"This image shows {phrase}"]
    ctx = (event_context or "").strip()
    if ctx:
        parts.append(f"for {ctx}")
    text = " ".join(parts) + "."
    alt = (alt_description or "").strip()
    if alt and not alt.startswith("[MOCK]"):
        text += f" {alt}"
    # Context is only as trustworthy as the state classification that produced it.
    context_confidence = round(0.85 * float(state_confidence), 4)
    return text, context_confidence


# Fallback copy (matches the app's legacy per-field defaults) when the LLM path is unavailable.
_DEFAULT_COPY = {
    "kicker": "PRODUCTION",
    "headline": "CRAFT IN EXECUTION",
    "sub": "Unseen architecture working behind the scene.",
}


def refine_copy(analyses: List) -> List[dict]:
    """Turn each image's OWN grounded event_context into {kicker,headline,sub}, index-aligned to
    `analyses` (i.e. to the computed sequence order). Runs AFTER ordering and is given no ability
    to reorder. Reuses the existing generate_slide_copy Node path (count=1 per image, so each
    image's copy is grounded in its own detected state). Never raises (generate_slide_copy
    already degrades to [MOCK] copy on any failure)."""
    out = []
    for a in analyses:
        ctx = getattr(a, "event_context", "") or getattr(a, "phase_summary", "")
        slides = generate_slide_copy(ctx, 1)
        copy = slides[0] if slides else dict(_DEFAULT_COPY)
        out.append({
            "kicker": copy.get("kicker") or _DEFAULT_COPY["kicker"],
            "headline": copy.get("headline") or _DEFAULT_COPY["headline"],
            "sub": copy.get("sub") or _DEFAULT_COPY["sub"],
        })
    return out
