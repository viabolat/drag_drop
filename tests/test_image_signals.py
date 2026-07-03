"""CV / EXIF / perceptual-hash primitive tests — real procedural images, no LLM."""
import pytest

from image_signals import extract_cv_signals, extract_metadata, perceptual_hash, hamming

pytestmark = pytest.mark.unit


def test_brightness_mean_tracks_fill(make_phase_jpeg):
    dark = extract_cv_signals(make_phase_jpeg("dark", brightness=30))
    bright = extract_cv_signals(make_phase_jpeg("bright", brightness=220))
    assert bright["brightness_mean"].value > dark["brightness_mean"].value


def test_clutter_raises_sharpness_and_edge_density(make_phase_jpeg):
    flat = extract_cv_signals(make_phase_jpeg("flat", brightness=128, clutter=0))
    busy = extract_cv_signals(make_phase_jpeg("busy", brightness=128, clutter=40))
    assert busy["sharpness_var"].value > flat["sharpness_var"].value
    assert busy["edge_density"].value > flat["edge_density"].value


def test_colorfulness_tracks_saturation(make_phase_jpeg):
    gray = extract_cv_signals(make_phase_jpeg("gray", brightness=128, clutter=30, colorfulness=0))
    color = extract_cv_signals(make_phase_jpeg("color", brightness=128, clutter=30, colorfulness=1))
    assert color["colorfulness"].value > gray["colorfulness"].value


def test_cv_signals_are_cv_sourced(make_phase_jpeg):
    sig = extract_cv_signals(make_phase_jpeg("x"))
    assert all(r.source == "cv" for r in sig.values())


def test_exif_datetime_original_read_from_jpeg(make_phase_jpeg):
    meta = extract_metadata(make_phase_jpeg("withexif", exif_dt="2024:06:01 18:30:00"))
    assert meta["has_exif"] is True
    assert meta["datetime_original"].year == 2024
    assert meta["datetime_original"].hour == 18


def test_png_has_no_exif(make_phase_jpeg):
    meta = extract_metadata(make_phase_jpeg("nopng", fmt="PNG"))
    assert meta["has_exif"] is False
    assert meta["datetime_original"] is None


def test_perceptual_hash_flags_near_duplicates(make_phase_jpeg):
    a = perceptual_hash(make_phase_jpeg("dup_a", brightness=128, clutter=10))
    b = perceptual_hash(make_phase_jpeg("dup_b", brightness=128, clutter=10))
    far = perceptual_hash(make_phase_jpeg("far", brightness=250, clutter=0))
    assert hamming(a, b) < hamming(a, far)


def test_signals_never_raise_on_bad_path():
    assert extract_cv_signals("/nonexistent/x.jpg") == {}
    assert extract_metadata("/nonexistent/x.jpg") == {"has_exif": False, "datetime_original": None}
    assert perceptual_hash("/nonexistent/x.jpg") is None
    assert hamming(None, 5) == 64
