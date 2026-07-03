"""Endpoint integration tests for /analyze-sequence/ and the /generate-post/ keyed path.
The vision analyzer is patched to a DictVisionAnalyzer, so Claude/node is never invoked."""
import json
import os

import pytest

from app import UPLOAD_DIR
from vision_provider import DictVisionAnalyzer

pytestmark = pytest.mark.integration


def _tp(name):
    return os.path.join(UPLOAD_DIR, name)


def _files(make_jpeg_bytes, *names):
    return [("files", (n, make_jpeg_bytes(), "image/jpeg")) for n in names]


def test_analyze_sequence_orders_and_returns_full_schema(client, mocker, make_signals, make_jpeg_bytes):
    mapping = {
        _tp("venue.jpg"): make_signals(vr=0.05, av=0.02, dec=0.02, pol=0.7),
        _tp("mid.jpg"): make_signals(vr=0.55, av=0.6, dec=0.45, pol=0.4, activity="crew"),
        _tp("live.jpg"): make_signals(vr=0.9, av=0.9, dec=0.9, pol=0.3, live=0.9, activity="audience"),
    }
    mocker.patch("app.get_vision_analyzer", return_value=DictVisionAnalyzer(mapping))
    # deliberately uploaded out of lifecycle order
    resp = client.post("/analyze-sequence/", data={"event_context": "gala"},
                       files=_files(make_jpeg_bytes, "live.jpg", "venue.jpg", "mid.jpg"))
    assert resp.status_code == 200
    analyses = resp.json()["analyses"]
    by_ref = {a["image_ref"]: a for a in analyses}
    assert (by_ref["venue.jpg"]["sequence_index"] < by_ref["mid.jpg"]["sequence_index"]
            < by_ref["live.jpg"]["sequence_index"])
    assert by_ref["venue.jpg"]["state_label"] == "venue_only"
    assert by_ref["live.jpg"]["state_label"] == "live_event"
    for key in ("image_path", "state_label", "state_confidence", "sequence_index",
                "sequence_confidence", "ordering_rationale", "event_context",
                "context_confidence", "alt_description", "phase_summary", "signals_detected",
                "metadata_used", "ambiguity_flags", "review_required", "image_ref", "upload_index"):
        assert key in analyses[0]
    # uploads cleaned up
    assert os.listdir(UPLOAD_DIR) == []


def test_analyze_sequence_context_bound_to_right_image(client, mocker, make_signals, make_jpeg_bytes):
    mapping = {
        _tp("a.jpg"): make_signals(vr=0.05, av=0.02, dec=0.02, pol=0.7, alt="ALT_A"),
        _tp("b.jpg"): make_signals(vr=0.95, av=0.95, dec=0.92, pol=0.95, alt="ALT_B"),
    }
    mocker.patch("app.get_vision_analyzer", return_value=DictVisionAnalyzer(mapping))
    resp = client.post("/analyze-sequence/", data={"event_context": ""},
                       files=_files(make_jpeg_bytes, "b.jpg", "a.jpg"))
    by_ref = {a["image_ref"]: a for a in resp.json()["analyses"]}
    assert "ALT_A" in by_ref["a.jpg"]["event_context"]
    assert "ALT_B" in by_ref["b.jpg"]["event_context"]
    assert by_ref["a.jpg"]["state_label"] == "venue_only"
    assert by_ref["b.jpg"]["state_label"] == "final_ready"


def test_analyze_sequence_generate_copy_attaches_grounded_copy(client, mocker, make_signals, make_jpeg_bytes):
    mocker.patch("app.get_vision_analyzer",
                 return_value=DictVisionAnalyzer({_tp("a.jpg"): make_signals()}))
    mocker.patch("context_generation.generate_slide_copy",
                 return_value=[{"kicker": "K", "headline": "H", "sub": "S"}])
    resp = client.post("/analyze-sequence/",
                       data={"event_context": "x", "generate_copy": "true"},
                       files=_files(make_jpeg_bytes, "a.jpg"))
    a = resp.json()["analyses"][0]
    assert a["copy"] == {"kicker": "K", "headline": "H", "sub": "S"}


def test_analyze_sequence_vision_unavailable_routes_to_review(client, mocker, make_jpeg_bytes):
    # empty mapping -> DictVisionAnalyzer returns MOCK for every image -> review
    mocker.patch("app.get_vision_analyzer", return_value=DictVisionAnalyzer({}))
    resp = client.post("/analyze-sequence/", data={"event_context": ""},
                       files=_files(make_jpeg_bytes, "a.jpg"))
    a = resp.json()["analyses"][0]
    assert a["review_required"] is True
    assert "vision_unavailable" in a["ambiguity_flags"]


def test_generate_post_sequence_json_keyed_reorder(client, mocker, make_jpeg_bytes):
    captured = {}

    def fake_render(dataset, output_base_name=None, **kw):
        captured["ds"] = dataset
        return {"mp4": "o.mp4", "pdf": "o.pdf"}

    mocker.patch("app.render_post_package", side_effect=fake_render)
    sequence = [
        {"image_ref": "b.jpg", "sequence_index": 0, "kicker": "BK", "headline": "BH",
         "sub": "BS", "state_label": "venue_only"},
        {"image_ref": "a.jpg", "sequence_index": 1, "kicker": "AK", "headline": "AH",
         "sub": "AS", "state_label": "final_ready"},
    ]
    resp = client.post(
        "/generate-post/",
        data={"output_name": "test_output_seq", "sequence_json": json.dumps(sequence)},
        files=_files(make_jpeg_bytes, "a.jpg", "b.jpg"),  # uploaded a,b; sequence wants b,a
    )
    assert resp.status_code == 200
    ds = captured["ds"]
    # order follows sequence_index (keyed by image_ref, NOT upload order)
    assert [os.path.basename(s["path"]) for s in ds] == ["b.jpg", "a.jpg"]
    assert ds[0]["kicker"] == "BK" and ds[1]["kicker"] == "AK"
    assert ds[0]["scale_frac"] <= ds[1]["scale_frac"]  # climbing fader
    assert os.listdir(UPLOAD_DIR) == []


def test_generate_post_without_metadata_or_sequence_returns_400(client, make_jpeg_bytes):
    resp = client.post("/generate-post/", data={"output_name": "test_output_x"},
                       files=_files(make_jpeg_bytes, "a.jpg"))
    assert resp.status_code == 400
