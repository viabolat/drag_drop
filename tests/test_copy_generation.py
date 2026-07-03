"""Pure-function tests for the per-image copy layer (no HTTP, no node/Claude).

These lock in the fix for the repeated-text bug: copy is derived per image from that image's OWN
state + event_context, LLM copy is preferred only when real (not [MOCK]), and there is no shared
constant fallback.
"""
import types

import pytest

from context_generation import derive_default_copy, refine_copy

pytestmark = pytest.mark.unit


def _analysis(state_label, event_context, phase_summary=""):
    return types.SimpleNamespace(
        state_label=state_label, event_context=event_context, phase_summary=phase_summary)


def test_derive_default_copy_is_per_image_and_grounded():
    c1 = derive_default_copy("venue_only", "This image shows an empty venue for gala.", "Venue-only")
    c2 = derive_default_copy("live_event", "This image shows the live event in progress for gala.",
                             "Live event")
    assert c1 != c2
    assert c1["kicker"] != c2["kicker"]                       # kicker grounded in state
    assert c1["sub"] and c1["sub"] != c2["sub"]               # sub grounded in each image's context
    assert not c1["sub"].startswith("This image shows")       # templated lead-in stripped


def test_derive_default_copy_blank_sub_when_no_context():
    c = derive_default_copy("mid_setup", "", "")
    assert c["kicker"] and c["headline"]                      # state still yields kicker/headline
    assert c["sub"] == ""                                     # no context => blank sub, not a constant


def test_refine_copy_prefers_live_llm_copy(mocker):
    mocker.patch("context_generation.generate_slide_copy",
                 return_value=[{"kicker": "LIVEK", "headline": "LIVEH", "sub": "LIVES"}])
    out = refine_copy([_analysis("late_setup", "ctx", "Late setup")], use_llm=True)[0]
    assert out == {"kicker": "LIVEK", "headline": "LIVEH", "sub": "LIVES"}


def test_refine_copy_discards_mock_llm_for_derived(mocker):
    # A [MOCK] LLM result is uniform across images and would re-introduce the bug — must be dropped.
    mocker.patch("context_generation.generate_slide_copy",
                 return_value=[{"kicker": "[MOCK]", "headline": "[MOCK] Slide 1 Headline",
                                "sub": "[MOCK] set token"}])
    out = refine_copy([_analysis("late_setup",
                                 "This image shows a late-setup scene for gala.", "Late setup")],
                      use_llm=True)[0]
    assert not out["kicker"].startswith("[MOCK]")
    assert out["kicker"] == "FINAL DRESS"                     # fell through to the derived tier


def test_refine_copy_without_llm_is_distinct_per_image(mocker):
    # use_llm False must NOT call the bridge, and must still produce distinct per-image copy.
    spy = mocker.patch("context_generation.generate_slide_copy")
    analyses = [
        _analysis("venue_only", "This image shows an empty venue for gala.", "Venue-only"),
        _analysis("live_event", "This image shows the live event in progress for gala.", "Live"),
    ]
    out = refine_copy(analyses, use_llm=False)
    spy.assert_not_called()
    assert out[0] != out[1]
    assert out[0]["kicker"] and out[1]["kicker"]
