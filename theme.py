"""Single-active-theme brand configuration.

The built-in defaults below are a neutral, unbranded placeholder theme — they exist so the
tool renders something reasonable with zero configuration. Real per-client brands live as JSON
files in the ``brands/`` directory (e.g. ``brands/citiview.json``), each overriding any subset
of Theme fields. Exactly one brand is active per installation, selected by either:

  - ``ACTIVE_BRAND=citiview``            -> resolves to ``brands/citiview.json``
  - ``BRAND_CONFIG=/abs/or/relative/path`` -> resolves to that exact file (wins if both are set)

Either may be set in the shell or in the local ``.env`` (loaded below, before ``THEME`` is built);
a shell value wins over ``.env``. Neither env var set means: use the neutral built-in defaults,
unchanged. A missing or malformed brand file logs a warning and falls back to defaults — a bad
theme must never break a render.

Colors are ``[r, g, b]`` lists in JSON (converted to tuples here). ``*_path`` fields may be
relative — they resolve against the repo root (not against ``brands/``), so a brand file's own
``"logo_path": "assets/logo_cn_white.png"`` still points at the shared top-level assets/ dir.
The font defaults below point at the bundled, license-clean fonts in assets/ (Saira Condensed +
Barlow) since those are generic app assets, not any one client's IP. ``logo_path`` has no
default — with no client logo configured, the render pipeline should fall back to the
``brand_short`` / ``brand_full`` text marks instead.

There is deliberately no per-run/UI theme selection: one active theme per installation keeps
the render path deterministic.
"""
import dataclasses
import json
import logging
import os

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# reason: brand selection is env-driven and this module is imported directly (by compositor,
# by tests) without necessarily passing through app.py first — so .env must be loaded HERE,
# before THEME is built, or an ACTIVE_BRAND set only in .env would be silently ignored
# depending on import order. load_dotenv() never overrides an already-set shell env var.
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ASSETS_DIR = os.path.join(BASE_DIR, "assets")
_BRANDS_DIR = os.path.join(BASE_DIR, "brands")

_COLOR_FIELDS = ("accent_rgb", "pure_white", "silver_text", "stamp_text", "dim_text")
_PATH_FIELDS = ("display_font_path", "body_font_path", "logo_path")


@dataclasses.dataclass(frozen=True)
class Theme:
    # Palette + type treatment — neutral slate accent, not tied to any client brand.
    accent_rgb: tuple = (90, 98, 110)
    pure_white: tuple = (255, 255, 255)
    silver_text: tuple = (192, 192, 192)
    stamp_text: tuple = (210, 214, 220)
    dim_text: tuple = (120, 124, 130)
    shear: float = 0.16  # forward italic shear applied to headline text

    # Bundled generic app assets (fonts are open-license, not client IP).
    display_font_path: str = os.path.join(_ASSETS_DIR, "SairaCondensed-Bold.ttf")
    body_font_path: str = os.path.join(_ASSETS_DIR, "Barlow-Regular.ttf")
    # No default logo — an unconfigured installation renders brand_short/brand_full as text
    # instead. NOTE: verify compositor.py treats "" as "no logo, use text fallback" before
    # relying on this — confirm the empty-path branch is handled there, not just here.
    logo_path: str = ""
    logo_height: int = 96

    # End-card copy + contact block — generic placeholders until a brand file is supplied.
    tagline_1: str = "YOUR TAGLINE HERE"
    tagline_2: str = "YOUR SECOND LINE HERE"
    contact_url: str = "yourwebsite.com"
    contact_phone: str = "555-555-5555"

    # Text fallbacks when the logo asset is unavailable.
    brand_short: str = "YOUR BRAND"       # slide top-left fallback
    brand_full: str = "YOUR BRAND NAME"   # end-card fallback

    # Output naming
    default_output_base: str = "social_post"

    # Browser UI chrome
    ui_title: str = "Campaign Studio — Post Production Engine"
    ui_heading: str = "CAMPAIGN STUDIO"
    ui_subtitle: str = "Automated Multi-Format Brand Material Compiler"
    ui_default_output_name: str = "post"

    # Identity handed to the LLM bridges (prompt flavor only — never auth/config).
    brand_name: str = "Your Brand"
    brand_description: str = "a business that produces branded event/social recap content"


def _resolve_brand_path():
    """Decide which brand file (if any) is active. BRAND_CONFIG wins over ACTIVE_BRAND."""
    explicit = os.environ.get("BRAND_CONFIG")
    if explicit:
        return explicit if os.path.isabs(explicit) else os.path.join(BASE_DIR, explicit)

    active = os.environ.get("ACTIVE_BRAND")
    if active:
        # reason: keep this a plain filename lookup, not a path — brand names shouldn't be
        # able to escape brands/ via "../" segments.
        safe_name = os.path.basename(active)
        return os.path.join(_BRANDS_DIR, f"{safe_name}.json")

    return None


def _load_overrides():
    path = _resolve_brand_path()
    if not path:
        return {}
    if not os.path.exists(path):
        logger.warning("Brand config not found at %s — using built-in defaults.", path)
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("brand config must be a JSON object")
    except Exception:
        # reason: a malformed theme must degrade to the built-in brand, never break a render.
        logger.warning("Ignoring unreadable brand config at %s — using built-in defaults.",
                        path, exc_info=True)
        return {}

    known = {f.name for f in dataclasses.fields(Theme)}
    overrides = {}
    for key, value in raw.items():
        if key not in known:
            logger.warning("brand config: unknown field %r ignored", key)
            continue
        if key in _COLOR_FIELDS:
            value = tuple(value)
        elif key in _PATH_FIELDS and value and not os.path.isabs(value):
            value = os.path.join(BASE_DIR, value)
        overrides[key] = value
    return overrides


def load_theme():
    """Build the active Theme (defaults + optional brand file overrides). Never raises."""
    try:
        return Theme(**_load_overrides())
    except Exception:
        logger.warning("Invalid brand config values — using built-in defaults.", exc_info=True)
        return Theme()


THEME = load_theme()