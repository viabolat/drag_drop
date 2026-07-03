import pytest
from PIL import ImageFont

import compositor


@pytest.mark.unit
def test_display_font_is_bundled_and_loadable():
    assert ImageFont.truetype(compositor.DISPLAY_FONT_PATH, 62)


@pytest.mark.unit
def test_body_font_is_bundled_and_loadable():
    assert ImageFont.truetype(compositor.BODY_FONT_PATH, 26)


@pytest.mark.unit
def test_compositor_has_no_network_font_fallback():
    # reason: compositor used to download fonts from GitHub at render time and silently fall
    # back to Pillow's default bitmap font on any failure — locking in that fonts are now
    # bundled in-repo with zero runtime network dependency.
    assert "requests" not in dir(compositor)
