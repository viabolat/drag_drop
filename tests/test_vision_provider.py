"""Vision-provider seam tests — the Claude/node boundary is mocked; node is never invoked
(mirrors how test_text_generation.py mocks text_generation.subprocess.run)."""
import json

import pytest

import lifecycle_taxonomy as tax
from vision_provider import (
    ClaudeVisionAnalyzer, DictVisionAnalyzer, MOCK_SEMANTIC,
    safe_analyze, to_signal_vector,
)

pytestmark = pytest.mark.unit


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _Raiser:
    def analyze(self, image_path, event_context=""):
        raise RuntimeError("boom")


def test_dict_analyzer_returns_mapping(make_signals):
    sig = make_signals(vr=0.9)
    da = DictVisionAnalyzer({"p": sig})
    assert da.analyze("p")["venue_readiness"]["value"] == 0.9
    assert da.analyze("unknown") == MOCK_SEMANTIC  # default fallback


def test_safe_analyze_wraps_raising_analyzer():
    semantic, unavailable = safe_analyze(_Raiser(), "p")
    assert unavailable is True
    assert semantic == MOCK_SEMANTIC


def test_safe_analyze_detects_mock_vector():
    semantic, unavailable = safe_analyze(DictVisionAnalyzer({}), "p")
    assert unavailable is True


def test_safe_analyze_reports_available_for_real_signals(make_signals):
    semantic, unavailable = safe_analyze(DictVisionAnalyzer({"p": make_signals(conf=0.9)}), "p")
    assert unavailable is False


def test_to_signal_vector_maps_numeric_and_categorical(make_signals):
    sv = to_signal_vector(make_signals(vr=0.7, activity="crew", conf=0.8))
    assert sv["venue_readiness"].value == 0.7
    assert sv["venue_readiness"].source == "vision"
    assert sv["human_activity_type"].raw == "crew"
    assert sv["human_activity_type"].confidence == 0.8


def test_claude_analyzer_parses_success(mocker, make_signals, make_phase_jpeg):
    sem = make_signals(vr=0.6, av=0.7, activity="crew")
    mocker.patch("vision_provider.subprocess.run",
                 return_value=_FakeProc(0, json.dumps(sem)))
    out = ClaudeVisionAnalyzer().analyze(make_phase_jpeg("real"))
    assert out["venue_readiness"]["value"] == 0.6
    assert out["human_activity_type"]["value"] == "crew"


def test_claude_analyzer_mock_on_nonzero_exit(mocker, make_phase_jpeg):
    mocker.patch("vision_provider.subprocess.run",
                 return_value=_FakeProc(3, "", "Claude Code process exited with code 1"))
    out = ClaudeVisionAnalyzer().analyze(make_phase_jpeg("real"))
    assert out == MOCK_SEMANTIC


def test_claude_analyzer_mock_on_missing_node(mocker, make_phase_jpeg):
    mocker.patch("vision_provider.subprocess.run", side_effect=FileNotFoundError)
    out = ClaudeVisionAnalyzer().analyze(make_phase_jpeg("real"))
    assert out == MOCK_SEMANTIC


def test_claude_analyzer_retries_transient_then_succeeds(mocker, make_signals, make_phase_jpeg):
    sem = make_signals(vr=0.6, activity="crew")
    # first call fails (transient), second succeeds -> retry recovers it
    run = mocker.patch("vision_provider.subprocess.run",
                       side_effect=[_FakeProc(3, "", "process exited with code 1"),
                                    _FakeProc(0, json.dumps(sem))])
    mocker.patch("vision_provider.time.sleep")  # no real backoff delay in tests
    out = ClaudeVisionAnalyzer().analyze(make_phase_jpeg("real"))
    assert out["venue_readiness"]["value"] == 0.6
    assert run.call_count == 2


def test_claude_analyzer_no_retry_on_timeout(mocker, make_phase_jpeg):
    import subprocess as _sp
    run = mocker.patch("vision_provider.subprocess.run",
                       side_effect=_sp.TimeoutExpired(cmd="node", timeout=90))
    out = ClaudeVisionAnalyzer().analyze(make_phase_jpeg("real"))
    assert out == MOCK_SEMANTIC
    assert run.call_count == 1  # timeout is not retried


def test_claude_analyzer_mock_on_malformed_json(mocker, make_phase_jpeg):
    mocker.patch("vision_provider.subprocess.run",
                 return_value=_FakeProc(0, "not json at all"))
    out = ClaudeVisionAnalyzer().analyze(make_phase_jpeg("real"))
    assert out == MOCK_SEMANTIC


def test_claude_analyzer_mock_on_bad_image_path(mocker):
    spy = mocker.patch("vision_provider.subprocess.run")
    out = ClaudeVisionAnalyzer().analyze("/nonexistent/image.jpg")
    assert out == MOCK_SEMANTIC
    spy.assert_not_called()  # downscale fails first; node is never invoked


def test_validate_semantic_rejects_missing_field(mocker, make_signals, make_phase_jpeg):
    bad = make_signals()
    del bad["teardown_cue"]
    mocker.patch("vision_provider.subprocess.run",
                 return_value=_FakeProc(0, json.dumps(bad)))
    out = ClaudeVisionAnalyzer().analyze(make_phase_jpeg("real"))
    assert out == MOCK_SEMANTIC
