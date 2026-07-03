import json
import time

import pytest


@pytest.mark.performance
def test_generate_post_completes_within_generous_ceiling(client, mock_ffmpeg_success, mock_fonts_present, make_jpeg_bytes):
    # reason: this endpoint does real Pillow compositing across two 1080x1350 canvases plus a
    # multi-page PDF save, so a generic <200ms threshold doesn't fit — 5s is a CI-safe ceiling
    # that still catches a real regression (e.g. an accidental O(n^2) loop).
    files = [
        ("files", ("slide_a.jpg", make_jpeg_bytes((200, 30, 30)), "image/jpeg")),
        ("files", ("slide_b.jpg", make_jpeg_bytes((30, 30, 200)), "image/jpeg")),
    ]
    metadata = [
        {"kicker": "ARENA", "headline": "LIGHTS UP", "sub": "Live setup."},
        {"kicker": "TOUR", "headline": "SOUND CHECK", "sub": "Final mix pass."},
    ]
    start = time.perf_counter()
    client.post(
        "/generate-post/",
        data={"output_name": "test_output_perf", "metadata_json": json.dumps(metadata)},
        files=files,
    )
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0
