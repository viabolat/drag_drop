import io
import json
import os

import pytest
from PIL import UnidentifiedImageError

from app import UPLOAD_DIR


@pytest.mark.integration
def test_malformed_metadata_json_returns_400(client, make_jpeg_bytes):
    files = [("files", ("slide_a.jpg", make_jpeg_bytes(), "image/jpeg"))]
    response = client.post(
        "/generate-post/",
        data={"output_name": "test_output_bad_json", "metadata_json": "{not valid json"},
        files=files,
    )
    assert response.status_code == 400


@pytest.mark.integration
def test_malformed_metadata_json_detail_message(client, make_jpeg_bytes):
    files = [("files", ("slide_a.jpg", make_jpeg_bytes(), "image/jpeg"))]
    response = client.post(
        "/generate-post/",
        data={"output_name": "test_output_bad_json", "metadata_json": "{not valid json"},
        files=files,
    )
    assert response.json()["detail"] == "Invalid data shape arrays."


@pytest.mark.integration
def test_missing_files_field_returns_422(client):
    response = client.post(
        "/generate-post/",
        data={"output_name": "test_output_no_files", "metadata_json": "[]"},
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_success_path_leaves_upload_dir_empty(posted_response):
    assert os.listdir(UPLOAD_DIR) == []


@pytest.mark.integration
def test_success_path_produces_pdf_on_disk(posted_response):
    # reason: outputs now follow the outputs/<base>/<base>.pdf convention, never project root
    assert os.path.exists(os.path.join("outputs", "test_output_posted", "test_output_posted.pdf"))


@pytest.mark.integration
def test_invalid_image_upload_is_skipped_not_crash(client, mock_fonts_present):
    # reason: R1 fixed — a corrupt-but-present image is skipped in the compositor and never raises
    # UnidentifiedImageError. With no valid frames left, the endpoint returns a controlled 500
    # "Render generation fault", not an uncaught crash/traceback.
    files = [("files", ("slide_a.jpg", io.BytesIO(b"not a real image"), "image/jpeg"))]
    metadata = [{"kicker": "ARENA", "headline": "LIGHTS UP", "sub": "Live setup."}]
    resp = client.post(
        "/generate-post/",
        data={"output_name": "test_output_invalid_image", "metadata_json": json.dumps(metadata)},
        files=files,
    )
    assert resp.status_code == 500
    assert "Render generation fault" in resp.json()["detail"]
    assert os.listdir(UPLOAD_DIR) == []


@pytest.mark.integration
def test_ffmpeg_missing_still_returns_success_response(client, mock_ffmpeg_missing, mock_fonts_present, make_jpeg_bytes):
    files = [("files", ("slide_a.jpg", make_jpeg_bytes(), "image/jpeg"))]
    metadata = [{"kicker": "ARENA", "headline": "LIGHTS UP", "sub": "Live setup."}]
    response = client.post(
        "/generate-post/",
        data={"output_name": "test_output_no_ffmpeg", "metadata_json": json.dumps(metadata)},
        files=files,
    )
    assert response.status_code == 200
    message = response.json()["message"]
    # R9: the response must not name an mp4 path that was never written.
    assert "test_output_no_ffmpeg.mp4" not in message
    assert "test_output_no_ffmpeg.pdf" in message
    assert "MP4 not produced" in message
