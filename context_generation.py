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


# Per-macro-phase brand copy. The kicker/headline are grounded in THIS image's detected state
# (a different state => different copy), never a single shared constant; the sub is grounded in
# the image's own event_context below, so it varies per image even within one phase. This is the
# tier-2 fallback that guarantees "different images -> different text" with no LLM in the loop.
_PHASE_KICKER = {
    "venue_only": "THE VENUE",
    "pre_setup": "LOAD-IN",
    "early_setup": "THE BUILD",
    "mid_setup": "THE BUILD",
    "late_setup": "FINAL DRESS",
    "final_ready": "DOORS",
    "live_event": "SHOWTIME",
    "post_event_teardown": "STRIKE",
    tax.AMBIGUOUS: "PRODUCTION",
}

_PHASE_HEADLINE = {
    "venue_only": "Where it all begins",
    "pre_setup": "Gear hits the floor",
    "early_setup": "Structure goes up",
    "mid_setup": "The room takes shape",
    "late_setup": "Down to the details",
    "final_ready": "Ready for the room",
    "live_event": "The moment, live",
    "post_event_teardown": "A clean strike",
    tax.AMBIGUOUS: "Craft in execution",
}


def _sub_from_context(event_context: str) -> str:
    """Ethos sub-line grounded in the image's OWN event_context (so it differs per image). Strips
    the templated lead-in and caps length; returns '' when there is no grounded context."""
    ctx = (event_context or "").strip()
    lead = "This image shows "
    if ctx.startswith(lead):
        ctx = ctx[len(lead):]
    ctx = ctx.strip().rstrip(".")
    if not ctx:
        return ""
    ctx = ctx[0].upper() + ctx[1:]
    return ctx[:140].strip()


def derive_default_copy(state_label: str, event_context: str, phase_summary: str = "") -> dict:
    """Deterministic per-image fallback copy grounded in THIS image's detected state + context.
    Two images with a different state or a different event_context get different copy — there is
    no shared brand constant. Used as the tier-2 fallback beneath live LLM copy."""
    kicker = _PHASE_KICKER.get(state_label) or "PRODUCTION"
    headline = _PHASE_HEADLINE.get(state_label) or (phase_summary or "").strip() or "Craft in execution"
    return {"kicker": kicker, "headline": headline, "sub": _sub_from_context(event_context)}


def _is_mock_copy(copy: dict) -> bool:
    """True if the LLM path fell back to its [MOCK] placeholder — never trust it over derived copy
    (the [MOCK] fallback is uniform across images and would re-introduce the repeated-text bug)."""
    return any(str(copy.get(k, "")).startswith("[MOCK]") for k in ("kicker", "headline", "sub"))


def refine_copy(analyses: List, use_llm: bool = True) -> List[dict]:
    """Per-image {kicker,headline,sub}, index-aligned to `analyses` (i.e. the computed sequence
    order). Runs AFTER ordering, with no ability to reorder. Each field resolves by priority:

        1. live grounded LLM copy for THIS image  (only when use_llm and not a [MOCK] fallback)
        2. deterministic per-image copy derived from THIS image's state_label + event_context
        3. '' (blank)                              — only if neither yields text

    So different images get different copy without any shared constant. Never raises
    (generate_slide_copy already degrades safely; a mock result is discarded in favor of tier 2)."""
    out = []
    for a in analyses:
        state_label = getattr(a, "state_label", "") or ""
        event_context = getattr(a, "event_context", "") or ""
        phase = getattr(a, "phase_summary", "") or ""
        derived = derive_default_copy(state_label, event_context, phase)

        llm = None
        if use_llm:
            ctx = event_context or phase
            slides = generate_slide_copy(ctx, 1)  # count=1: copy grounded in this image's context
            cand = slides[0] if slides else None
            if isinstance(cand, dict) and not _is_mock_copy(cand):
                llm = cand

        copy = {}
        for field in ("kicker", "headline", "sub"):
            if llm and str(llm.get(field, "")).strip():
                copy[field] = llm[field]
            elif str(derived.get(field, "")).strip():
                copy[field] = derived[field]
            else:
                copy[field] = ""
        out.append(copy)
    return out
