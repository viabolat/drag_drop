import glob
import io
import json
import os
import shutil

import pytest
from fastapi.testclient import TestClient
from PIL import Image

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
