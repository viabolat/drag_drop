import json

import pytest

import text_generation


def _fake_completed_process(returncode=0, stdout="", stderr=""):
    class FakeResult:
        pass
    result = FakeResult()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


@pytest.mark.unit
def test_zero_slide_count_returns_empty_list():
    assert text_generation.generate_slide_copy("context", 0) == []


@pytest.mark.unit
def test_node_script_success_parses_json(mocker):
    slides = [{"kicker": "Live Now", "headline": "Lights Up", "sub": "Doors open at 7."}]
    mocker.patch(
        "text_generation.subprocess.run",
        return_value=_fake_completed_process(stdout=json.dumps(slides)),
    )
    result = text_generation.generate_slide_copy("Corporate gala", 1)
    assert result == slides


@pytest.mark.unit
def test_node_script_nonzero_exit_falls_back_to_mock(mocker):
    mocker.patch(
        "text_generation.subprocess.run",
        return_value=_fake_completed_process(returncode=2, stderr="ANTHROPIC_API_KEY is set..."),
    )
    slides = text_generation.generate_slide_copy("Corporate gala", 2)
    assert len(slides) == 2
    assert all(s["kicker"] == "[MOCK]" for s in slides)


@pytest.mark.unit
def test_node_executable_missing_falls_back_to_mock(mocker):
    mocker.patch("text_generation.subprocess.run", side_effect=FileNotFoundError)
    slides = text_generation.generate_slide_copy("Corporate gala", 2)
    assert len(slides) == 2
    assert all(s["kicker"] == "[MOCK]" for s in slides)


@pytest.mark.unit
def test_malformed_stdout_falls_back_to_mock(mocker):
    mocker.patch(
        "text_generation.subprocess.run",
        return_value=_fake_completed_process(stdout="not json"),
    )
    slides = text_generation.generate_slide_copy("Corporate gala", 2)
    assert len(slides) == 2
    assert all(s["kicker"] == "[MOCK]" for s in slides)


@pytest.mark.unit
def test_mismatched_slide_count_falls_back_to_mock(mocker):
    mocker.patch(
        "text_generation.subprocess.run",
        return_value=_fake_completed_process(stdout=json.dumps([{"kicker": "K", "headline": "H", "sub": "S"}])),
    )
    slides = text_generation.generate_slide_copy("Corporate gala", 3)
    assert len(slides) == 3
    assert all(s["kicker"] == "[MOCK]" for s in slides)
