import glob
import io
import json
import os
import shutil

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app import app, UPLOAD_DIR

# Final deliverables land under outputs/<base>/; legacy root globs kept as belt-and-suspenders.
OUTPUT_GLOBS = ("test_output*.pdf", "test_output*.mp4", "__ui_slide_*.jpg", "ui_input.txt")
OUTPUT_DIR_GLOB = os.path.join("outputs", "test_output*")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def client_no_raise():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def make_jpeg_bytes():
    def _make(color=(200, 30, 30), size=(64, 64)):
        buf = io.BytesIO()
        Image.new("RGB", size, color).save(buf, "JPEG")
        buf.seek(0)
        return buf
    return _make


@pytest.fixture
def mock_ffmpeg_success(mocker):
    return mocker.patch("compositor.subprocess.run", return_value=None)


@pytest.fixture
def mock_ffmpeg_missing(mocker):
    return mocker.patch("compositor.subprocess.run", side_effect=FileNotFoundError)


@pytest.fixture
def mock_fonts_present(mocker):
    return mocker.patch("compositor.os.path.exists", return_value=True)


@pytest.fixture
def posted_response(client, mock_ffmpeg_success, mock_fonts_present, make_jpeg_bytes):
    files = [
        ("files", ("slide_a.jpg", make_jpeg_bytes((200, 30, 30)), "image/jpeg")),
        ("files", ("slide_b.jpg", make_jpeg_bytes((30, 30, 200)), "image/jpeg")),
    ]
    metadata = [
        {"kicker": "ARENA", "headline": "LIGHTS UP", "sub": "Live setup in progress."},
        {"kicker": "TOUR", "headline": "SOUND CHECK", "sub": "Final mix pass."},
    ]
    return client.post(
        "/generate-post/",
        data={"output_name": "test_output_posted", "metadata_json": json.dumps(metadata)},
        files=files,
    )


@pytest.fixture
def make_signals():
    """Build a raw vision-semantic dict (the analyze_image.mjs output shape) for injecting
    deterministic per-image signals into the lifecycle engine (via DictVisionAnalyzer)."""
    def _make(vr=0.5, av=0.5, dec=0.5, pol=0.5, live=0.0, tear=0.0,
              activity="none", conf=0.9, alt="an event image", labels=None):
        return {
            "venue_readiness": {"value": vr, "confidence": conf},
            "av_staging_completeness": {"value": av, "confidence": conf},
            "decor_completeness": {"value": dec, "confidence": conf},
            "polish_vs_clutter": {"value": pol, "confidence": conf},
            "live_event_cue": {"value": live, "confidence": conf},
            "teardown_cue": {"value": tear, "confidence": conf},
            "human_activity_type": {"value": activity, "confidence": conf},
            "alt_description": alt,
            "raw_labels": labels or ["a", "b"],
        }
    return _make


@pytest.fixture
def make_phase_jpeg(tmp_path):
    """Procedurally synthesize a phase-distinguishable image on disk (returns its path).

    `clutter` draws many small rectangles/lines -> higher Laplacian variance + edge density;
    `colorfulness` toggles saturated fills; `exif_dt` (JPEG only) embeds DateTimeOriginal.
    """
    def _make(name="img", brightness=128, clutter=0, colorfulness=0, exif_dt=None, fmt="JPEG"):
        size = (256, 256)
        img = Image.new("RGB", size, (brightness, brightness, brightness))
        d = ImageDraw.Draw(img)
        for i in range(clutter):
            x, y = (i * 37) % size[0], (i * 53) % size[1]
            col = ((i * 90) % 256, (i * 150) % 256, (i * 210) % 256) if colorfulness \
                else (brightness, brightness, brightness)
            d.rectangle([x, y, x + 8, y + 8], fill=col)
            d.line([x, y, x + 20, y + 20], fill=(255, 0, 0) if colorfulness else (0, 0, 0))
        ext = "jpg" if fmt == "JPEG" else "png"
        path = tmp_path / f"{name}.{ext}"
        kwargs = {}
        if exif_dt and fmt == "JPEG":
            exif = Image.Exif()
            exif[36867] = exif_dt
            kwargs["exif"] = exif.tobytes()
        img.save(str(path), fmt, **kwargs)
        return str(path)
    return _make


@pytest.fixture(autouse=True)
def cleanup_artifacts():
    yield
    for pattern in OUTPUT_GLOBS:
        for path in glob.glob(pattern):
            os.remove(path)
    for path in glob.glob(OUTPUT_DIR_GLOB):
        shutil.rmtree(path, ignore_errors=True)
    for name in os.listdir(UPLOAD_DIR):
        os.remove(os.path.join(UPLOAD_DIR, name))
