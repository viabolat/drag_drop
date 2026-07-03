"""
Security tests scoped to what actually exists in this app.

N/A for this codebase (verified via full-repo grep, no code paths to test):
- SQL injection: no database/ORM/raw queries anywhere.
- Authorization boundaries between users: no auth system, no user model.
"""
import io
import json
import os

import pytest
from fastapi import HTTPException

from app import sanitize_upload_filename, UPLOAD_DIR


@pytest.mark.security
@pytest.mark.unit
def test_path_traversal_filename_stays_within_upload_dir():
    result = sanitize_upload_filename("../../evil.jpg")
    assert os.path.abspath(result).startswith(os.path.abspath(UPLOAD_DIR) + os.sep)


@pytest.mark.security
@pytest.mark.unit
def test_dot_dot_filename_is_rejected():
    with pytest.raises(HTTPException):
        sanitize_upload_filename("..")


@pytest.mark.security
@pytest.mark.integration
def test_invalid_image_upload_500_body_has_no_traceback(client_no_raise, mock_fonts_present):
    files = [("files", ("slide_a.jpg", io.BytesIO(b"not a real image"), "image/jpeg"))]
    metadata = [{"kicker": "ARENA", "headline": "LIGHTS UP", "sub": "Live setup."}]
    response = client_no_raise.post(
        "/generate-post/",
        data={"output_name": "test_output_leak_check", "metadata_json": json.dumps(metadata)},
        files=files,
    )
    assert "Traceback" not in response.text


@pytest.mark.security
@pytest.mark.integration
def test_generate_post_reachable_without_authentication(posted_response):
    # reason: documents the intentional no-auth posture (single-operator local tool, see
    # docs/spec.md) so it's a visible, locked-in scope decision rather than an unexamined gap
    assert posted_response.status_code not in (401, 403)
