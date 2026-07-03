import json
import os

import pytest

from app import UPLOAD_DIR


@pytest.fixture
def mismatched_payload(make_jpeg_bytes):
    files = [
        ("files", ("slide_a.jpg", make_jpeg_bytes(), "image/jpeg")),
        ("files", ("slide_b.jpg", make_jpeg_bytes(), "image/jpeg")),
    ]
    metadata = [{"kicker": "ARENA", "headline": "LIGHTS UP", "sub": "Live setup."}]
    return {"output_name": "test_output_mismatch", "metadata_json": json.dumps(metadata)}, files


@pytest.mark.integration
def test_metadata_index_mismatch_raises_indexerror(client, mismatched_payload):
    data, files = mismatched_payload
    with pytest.raises(IndexError):
        client.post("/generate-post/", data=data, files=files)


@pytest.mark.integration
def test_metadata_index_mismatch_cleans_up_uploads(client, mismatched_payload):
    data, files = mismatched_payload
    with pytest.raises(IndexError):
        client.post("/generate-post/", data=data, files=files)
    assert os.listdir(UPLOAD_DIR) == []


@pytest.mark.integration
def test_success_response_has_status_key(posted_response):
    assert "status" in posted_response.json()


@pytest.mark.integration
def test_success_response_has_message_key(posted_response):
    assert "message" in posted_response.json()


@pytest.mark.integration
def test_success_message_references_pdf_output(posted_response):
    assert "test_output_posted.pdf" in posted_response.json()["message"]


@pytest.mark.integration
def test_success_message_references_mp4_output(posted_response):
    assert "test_output_posted.mp4" in posted_response.json()["message"]
