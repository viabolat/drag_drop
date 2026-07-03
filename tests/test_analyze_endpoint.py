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
    # uploaded a=u0, b=u1; the sequence wants b then a — joined by uid, NOT basename/upload order
    sequence = [
        {"uid": "u1", "image_ref": "b.jpg", "sequence_index": 0, "kicker": "BK", "headline": "BH",
         "sub": "BS", "state_label": "venue_only"},
        {"uid": "u0", "image_ref": "a.jpg", "sequence_index": 1, "kicker": "AK", "headline": "AH",
         "sub": "AS", "state_label": "final_ready"},
    ]
    resp = client.post(
        "/generate-post/",
        data={"output_name": "test_output_seq", "sequence_json": json.dumps(sequence),
              "upload_uids": json.dumps(["u0", "u1"])},
        files=_files(make_jpeg_bytes, "a.jpg", "b.jpg"),
    )
    assert resp.status_code == 200
    ds = captured["ds"]
    # order follows sequence_index (keyed by uid, NOT upload order or basename)
    assert [os.path.basename(s["path"]) for s in ds] == ["b.jpg", "a.jpg"]
    assert ds[0]["kicker"] == "BK" and ds[1]["kicker"] == "AK"
    assert ds[0]["scale_frac"] <= ds[1]["scale_frac"]  # climbing fader
    assert os.listdir(UPLOAD_DIR) == []


def test_generate_post_duplicate_basenames_stay_distinct(client, mocker, make_jpeg_bytes):
    """Two DIFFERENT images sharing the basename 'photo.jpg' must render as two distinct slides
    (distinct on-disk paths + their own copy) — never collapse to one reused image."""
    captured = {}

    def fake_render(dataset, output_base_name=None, **kw):
        captured["ds"] = dataset
        return {"mp4": "o.mp4", "pdf": "o.pdf"}

    mocker.patch("app.render_post_package", side_effect=fake_render)
    files = [("files", ("photo.jpg", make_jpeg_bytes((10, 10, 10)), "image/jpeg")),
             ("files", ("photo.jpg", make_jpeg_bytes((240, 240, 240)), "image/jpeg"))]
    sequence = [
        {"uid": "u0", "image_ref": "photo.jpg", "sequence_index": 0,
         "kicker": "FIRST", "headline": "H0", "sub": "S0"},
        {"uid": "u1", "image_ref": "photo.jpg", "sequence_index": 1,
         "kicker": "SECOND", "headline": "H1", "sub": "S1"},
    ]
    resp = client.post(
        "/generate-post/",
        data={"output_name": "test_output_dup", "sequence_json": json.dumps(sequence),
              "upload_uids": json.dumps(["u0", "u1"])},
        files=files,
    )
    assert resp.status_code == 200
    ds = captured["ds"]
    assert len(ds) == 2                      # not collapsed into a single image
    assert ds[0]["path"] != ds[1]["path"]    # two distinct files on disk
    assert [s["kicker"] for s in ds] == ["FIRST", "SECOND"]
    assert os.listdir(UPLOAD_DIR) == []


def test_generate_post_sequence_blank_copy_stays_blank(client, mocker, make_jpeg_bytes):
    """An intentionally blanked field renders no overlay text — never the old shared constant."""
    captured = {}

    def fake_render(dataset, output_base_name=None, **kw):
        captured["ds"] = dataset
        return {"mp4": "o.mp4", "pdf": "o.pdf"}

    mocker.patch("app.render_post_package", side_effect=fake_render)
    sequence = [{"uid": "u0", "image_ref": "a.jpg", "sequence_index": 0,
                 "kicker": "", "headline": "", "sub": ""}]
    resp = client.post(
        "/generate-post/",
        data={"output_name": "test_output_blank", "sequence_json": json.dumps(sequence),
              "upload_uids": json.dumps(["u0"])},
        files=_files(make_jpeg_bytes, "a.jpg"),
    )
    assert resp.status_code == 200
    s = captured["ds"][0]
    assert s["kicker"] == "" and s["headline"] == "" and s["sub"] == ""
    assert "PRODUCTION" not in (s["kicker"], s["headline"], s["sub"])
    assert os.listdir(UPLOAD_DIR) == []


def test_generate_post_sequence_requires_upload_uids(client, make_jpeg_bytes):
    sequence = [{"uid": "u0", "image_ref": "a.jpg", "sequence_index": 0,
                 "kicker": "K", "headline": "H", "sub": "S"}]
    resp = client.post(
        "/generate-post/",
        data={"output_name": "test_output_nouids", "sequence_json": json.dumps(sequence)},
        files=_files(make_jpeg_bytes, "a.jpg"),
    )
    assert resp.status_code == 400  # fail loudly: no uid<->file alignment provided


def test_generate_post_sequence_uid_file_length_mismatch(client, make_jpeg_bytes):
    sequence = [{"uid": "u0", "image_ref": "a.jpg", "sequence_index": 0,
                 "kicker": "K", "headline": "H", "sub": "S"}]
    resp = client.post(
        "/generate-post/",
        data={"output_name": "test_output_mis", "sequence_json": json.dumps(sequence),
              "upload_uids": json.dumps(["u0", "u1"])},  # 2 uids, 1 file
        files=_files(make_jpeg_bytes, "a.jpg"),
    )
    assert resp.status_code == 400  # fail loudly: misaligned


def test_generate_post_sequence_unknown_uid(client, make_jpeg_bytes):
    sequence = [{"uid": "uX", "image_ref": "a.jpg", "sequence_index": 0,
                 "kicker": "K", "headline": "H", "sub": "S"}]
    resp = client.post(
        "/generate-post/",
        data={"output_name": "test_output_unk", "sequence_json": json.dumps(sequence),
              "upload_uids": json.dumps(["u0"])},
        files=_files(make_jpeg_bytes, "a.jpg"),
    )
    assert resp.status_code == 400  # fail loudly: entry uid has no matching upload


def test_analyze_sequence_attaches_distinct_derived_copy_without_llm(
        client, mocker, make_signals, make_jpeg_bytes):
    """With auto-copy OFF (no LLM), per-image copy is STILL attached and distinct per state —
    proving the repeated-shared-constant collapse is gone at the source."""
    mapping = {
        _tp("venue.jpg"): make_signals(vr=0.05, av=0.02, dec=0.02, pol=0.7),
        _tp("live.jpg"): make_signals(vr=0.9, av=0.9, dec=0.9, pol=0.3, live=0.9, activity="audience"),
    }
    mocker.patch("app.get_vision_analyzer", return_value=DictVisionAnalyzer(mapping))
    resp = client.post("/analyze-sequence/", data={"event_context": "gala"},
                       files=_files(make_jpeg_bytes, "venue.jpg", "live.jpg"))
    by_ref = {a["image_ref"]: a for a in resp.json()["analyses"]}
    cv, cl = by_ref["venue.jpg"]["copy"], by_ref["live.jpg"]["copy"]
    assert cv["kicker"] and cl["kicker"]                              # never blank
    assert (cv["kicker"], cv["headline"]) != (cl["kicker"], cl["headline"])  # per-state distinct
    assert cv["sub"] and cv["sub"] != cl["sub"]                      # sub grounded per image


def test_full_flow_reorder_preserves_text_image_binding(
        client, mocker, make_signals, make_jpeg_bytes):
    """End-to-end: analyze 3 distinct images -> scramble the sequence -> generate. Each slide must
    keep ITS OWN copy bound to ITS OWN image after the reorder (joined by uid, not position)."""
    mapping = {
        _tp("venue.jpg"): make_signals(vr=0.05, av=0.02, dec=0.02, pol=0.7, alt="EMPTY_ROOM"),
        _tp("mid.jpg"): make_signals(vr=0.55, av=0.6, dec=0.45, pol=0.4, activity="crew", alt="CREW_RIG"),
        _tp("live.jpg"): make_signals(vr=0.9, av=0.9, dec=0.9, pol=0.3, live=0.9,
                                      activity="audience", alt="CROWD"),
    }
    mocker.patch("app.get_vision_analyzer", return_value=DictVisionAnalyzer(mapping))
    # 1) analyze (auto-copy OFF -> per-image derived copy, still distinct)
    resp = client.post("/analyze-sequence/", data={"event_context": "gala"},
                       files=_files(make_jpeg_bytes, "venue.jpg", "mid.jpg", "live.jpg"))
    analyses = resp.json()["analyses"]
    # 2) mirror the frontend: uid assigned by UPLOAD order (upload_index), copy from each item
    uid_by_upload = {0: "u0", 1: "u1", 2: "u2"}
    expected_kicker = {}   # image_ref -> its own kicker
    seq = []
    for a in analyses:
        uid = uid_by_upload[a["upload_index"]]
        expected_kicker[a["image_ref"]] = a["copy"]["kicker"]
        seq.append({"uid": uid, "image_ref": a["image_ref"], "state_label": a["state_label"],
                    "kicker": a["copy"]["kicker"], "headline": a["copy"]["headline"],
                    "sub": a["copy"]["sub"]})
    # scramble: reverse the order, then (re)assign sequence_index to the scrambled positions
    seq = list(reversed(seq))
    for i, e in enumerate(seq):
        e["sequence_index"] = i

    captured = {}

    def fake_render(dataset, output_base_name=None, **kw):
        captured["ds"] = dataset
        return {"mp4": "o.mp4", "pdf": "o.pdf"}

    mocker.patch("app.render_post_package", side_effect=fake_render)
    # 3) generate — files in UPLOAD order + aligned uids; sequence carries the scrambled order
    resp = client.post(
        "/generate-post/",
        data={"output_name": "test_output_flow", "sequence_json": json.dumps(seq),
              "upload_uids": json.dumps(["u0", "u1", "u2"])},
        files=_files(make_jpeg_bytes, "venue.jpg", "mid.jpg", "live.jpg"),
    )
    assert resp.status_code == 200
    ds = captured["ds"]
    # order follows the scrambled sequence, and every slide's copy is still ITS image's copy
    assert [os.path.basename(s["path"]) for s in ds] == ["live.jpg", "mid.jpg", "venue.jpg"]
    for s in ds:
        assert s["kicker"] == expected_kicker[os.path.basename(s["path"])]
    # and the three images genuinely got different copy (no shared repeat)
    assert len({s["kicker"] + "|" + s["sub"] for s in ds}) == 3
    assert os.listdir(UPLOAD_DIR) == []


def test_generate_post_without_metadata_or_sequence_returns_400(client, make_jpeg_bytes):
    resp = client.post("/generate-post/", data={"output_name": "test_output_x"},
                       files=_files(make_jpeg_bytes, "a.jpg"))
    assert resp.status_code == 400
