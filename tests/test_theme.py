"""Theming seam — the built-in defaults are a neutral placeholder brand; activating the CitiView
brand must yield exactly the historical values; overrides must be safe (a broken or missing brand
file can never break a render)."""
import json
import os

import pytest
from PIL import Image

import theme
from theme import Theme, load_theme


@pytest.mark.unit
# reason: brands/*.json is gitignored per-installation config, so CI never has citiview.json and
# load_theme() falls back to neutral defaults — this check is only meaningful where the file exists.
@pytest.mark.skipif(not os.path.exists(os.path.join(theme._BRANDS_DIR, "citiview.json")),
                    reason="brands/citiview.json is local-only (gitignored)")
def test_active_brand_citiview_is_historical_brand(monkeypatch):
    # reason: these values are no longer the dataclass defaults — they live in
    # brands/citiview.json and are selected via ACTIVE_BRAND. Same assertions as when they
    # were defaults, so any drift in the shipped CitiView brand still fails here.
    monkeypatch.setenv("ACTIVE_BRAND", "citiview")
    t = load_theme()
    assert t.accent_rgb == (225, 29, 42)
    assert t.pure_white == (255, 255, 255)
    assert t.silver_text == (192, 192, 192)
    assert t.stamp_text == (210, 214, 220)
    assert t.dim_text == (120, 124, 130)
    assert t.shear == 0.16
    assert t.logo_height == 96
    assert t.tagline_1 == "FULL EVENT PRODUCTION · LIGHTING · STAGING"
    assert t.tagline_2 == "SOUND · VIDEO · STREAMING"
    assert t.contact_url == "CitiViewAV.com"
    assert t.contact_phone == "NY (212) 632-5196   CO (303) 414-2834"
    assert t.brand_short == "CITIVIEW AV"
    assert t.brand_full == "CITIVIEW AUDIO VISUAL"
    assert t.default_output_base == "citiview_social_post"
    assert t.display_font_path.endswith("SairaCondensed-Bold.ttf")
    assert t.body_font_path.endswith("Barlow-Regular.ttf")
    assert t.logo_path.endswith("logo_cn_white.png")


@pytest.mark.unit
def test_no_brand_selected_means_neutral_defaults():
    """With neither env var set (the conftest scrub guarantees this), the tool renders the
    unbranded placeholder theme — notably an empty logo_path, so no client asset is assumed."""
    t = load_theme()
    assert t == Theme()
    assert t.logo_path == ""
    assert t.brand_short == "YOUR BRAND"


@pytest.mark.unit
def test_compositor_constants_come_from_theme():
    # reason: compare against the ACTIVE theme (theme.THEME), not Theme() defaults — compositor
    # rebinds at import time from whatever brand was resolved, which may not be the defaults.
    import compositor
    t = theme.THEME
    assert compositor.ACCENT_RED == t.accent_rgb
    assert compositor.SHEAR == t.shear
    assert compositor.TAGLINE_1 == t.tagline_1
    assert compositor.CONTACT_URL == t.contact_url
    assert compositor.DISPLAY_FONT_PATH == t.display_font_path
    assert compositor.BODY_FONT_PATH == t.body_font_path


@pytest.mark.unit
def test_brand_file_overrides_subset(tmp_path, monkeypatch):
    cfg = tmp_path / "custom_brand.json"
    cfg.write_text(json.dumps({
        "accent_rgb": [10, 120, 200],
        "contact_url": "ExampleAV.com",
        "logo_path": "assets/logo_cn_white.png",  # relative -> resolves against repo root
        "ui_heading": "EXAMPLE AV — STUDIO",
    }))
    monkeypatch.setenv("BRAND_CONFIG", str(cfg))
    t = load_theme()
    assert t.accent_rgb == (10, 120, 200)
    assert t.contact_url == "ExampleAV.com"
    assert t.ui_heading == "EXAMPLE AV — STUDIO"
    assert t.logo_path == theme.BASE_DIR + "/assets/logo_cn_white.png"
    # Untouched fields keep the built-in defaults.
    assert t.tagline_1 == Theme().tagline_1
    assert t.contact_phone == Theme().contact_phone


@pytest.mark.unit
def test_brand_config_wins_over_active_brand(tmp_path, monkeypatch):
    """Precedence rule — easy to accidentally invert in a future edit, so pin it."""
    cfg = tmp_path / "custom_brand.json"
    cfg.write_text(json.dumps({"contact_url": "ExplicitPath.com"}))
    monkeypatch.setenv("ACTIVE_BRAND", "citiview")
    monkeypatch.setenv("BRAND_CONFIG", str(cfg))
    t = load_theme()
    assert t.contact_url == "ExplicitPath.com"
    assert t.brand_short == Theme().brand_short  # citiview.json was not consulted at all


@pytest.mark.unit
def test_unknown_active_brand_name_falls_back_to_defaults(monkeypatch):
    """A typo'd or not-yet-created brand name must degrade to defaults, never raise."""
    monkeypatch.setenv("ACTIVE_BRAND", "no_such_brand")
    assert load_theme() == Theme()


@pytest.mark.unit
def test_malformed_brand_file_falls_back_to_defaults(tmp_path, monkeypatch):
    cfg = tmp_path / "custom_brand.json"
    cfg.write_text("{not valid json")
    monkeypatch.setenv("BRAND_CONFIG", str(cfg))
    assert load_theme() == Theme()


@pytest.mark.unit
def test_unknown_fields_ignored_not_fatal(tmp_path, monkeypatch):
    cfg = tmp_path / "custom_brand.json"
    cfg.write_text(json.dumps({"contact_url": "ExampleAV.com", "no_such_field": 1}))
    monkeypatch.setenv("BRAND_CONFIG", str(cfg))
    t = load_theme()
    assert t.contact_url == "ExampleAV.com"


@pytest.mark.unit
def test_missing_brand_file_means_pure_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAND_CONFIG", str(tmp_path / "does_not_exist.json"))
    assert load_theme() == Theme()


@pytest.mark.unit
def test_empty_logo_path_degrades_to_brand_text(mocker):
    """The default theme ships logo_path == "" — compositor must treat that as "no logo" and
    stamp the brand_short / brand_full text marks instead (never render nothing, never crash)."""
    import compositor

    mocker.patch.object(compositor, "LOGO_PATH", "")
    assert compositor.load_logo() is None
    assert compositor._load_logo_full() is None

    fonts = {
        "display": compositor._font(compositor.DISPLAY_FONT_PATH, 92),
        "kicker": compositor._font(compositor.DISPLAY_FONT_PATH, 30),
        "sub": compositor._font(compositor.BODY_FONT_PATH, 30),
        "url": compositor._font(compositor.DISPLAY_FONT_PATH, 30),
        "stamp1": compositor._font(compositor.DISPLAY_FONT_PATH, 24),
        "stamp2": compositor._font(compositor.BODY_FONT_PATH, 15),
        "tag": compositor._font(compositor.BODY_FONT_PATH, 26),
        "contact": compositor._font(compositor.DISPLAY_FONT_PATH, 34),
        "foot": compositor._font(compositor.BODY_FONT_PATH, 22),
    }
    photo = Image.new("RGB", (compositor.OUTPUT_WIDTH, compositor.OUTPUT_HEIGHT), (40, 44, 50))

    # Slide: the fallback goes through ImageDraw.text — patch it so the call is observable
    # (drawing is suppressed, but the render must still complete without a logo).
    text_spy = mocker.patch.object(compositor.ImageDraw.ImageDraw, "text", autospec=True)
    frame, _ = compositor._compose_slide(photo, {"headline": "X"}, 0, 1, None, None, False, fonts)
    assert frame.size == (compositor.OUTPUT_WIDTH, compositor.OUTPUT_HEIGHT)
    assert any(compositor.THEME.brand_short in call.args for call in text_spy.call_args_list)

    # End card: the fallback goes through _render_line with the long-form brand mark.
    line_spy = mocker.spy(compositor, "_render_line")
    endcard = compositor._build_endcard(photo, None, None, fonts)
    assert endcard.size == (compositor.OUTPUT_WIDTH, compositor.OUTPUT_HEIGHT)
    assert any(call.args[0] == compositor.THEME.brand_full for call in line_spy.call_args_list)
