import os
import math
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter

from theme import THEME

# ---------------------------------------------------------------------------
# Canvas + brand palette. Brand values come from theme.py (neutral placeholder defaults,
# optionally overridden by the active brand file — brands/<name>.json via ACTIVE_BRAND, or any
# path via BRAND_CONFIG) — rebound to the historical module-level names so every draw call
# and external import (tests, app.py) keeps working unchanged.
# ---------------------------------------------------------------------------
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1350
ACCENT_RED = THEME.accent_rgb
PURE_WHITE = THEME.pure_white
SILVER_TEXT = THEME.silver_text
STAMP_TEXT = THEME.stamp_text
DIM_TEXT = THEME.dim_text
SHEAR = THEME.shear  # forward italic shear (tops lean right), applied to headline text

# reason: fonts + logo are bundled in-repo under assets/ (theme defaults anchor to this file's
# directory), so the render works regardless of the process CWD (server, tests, or a script).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
DISPLAY_FONT_PATH = THEME.display_font_path  # condensed display face
BODY_FONT_PATH = THEME.body_font_path
LOGO_PATH = THEME.logo_path
LOGO_HEIGHT = THEME.logo_height  # measured from reference: logo ink ~96px tall at pad (60, 52)

# Final deliverables land under outputs/<base>/ — never the project root.
OUTPUT_ROOT = os.path.join(BASE_DIR, "outputs")

# End-card brand copy (from the active theme).
TAGLINE_1 = THEME.tagline_1
TAGLINE_2 = THEME.tagline_2
CONTACT_URL = THEME.contact_url
CONTACT_PHONE = THEME.contact_phone

# Neutral house grade + crop — mild by default (the tool has no per-event look), but every
# slide dict may override via optional "grade"/"crop" keys without breaking the contract.
DEFAULT_GRADE = dict(exposure=1.03, contrast=1.08, saturation=1.08, sharpen=0.4, cool=0.0)
DEFAULT_CROP = dict(focus_x=0.5, focus_y=0.42, zoom=1.0)

# MP4 spec (locked): 1080x1350, 30fps, silent, H.264/yuv420p, static holds + crossfades.
HOLD_SECONDS = 4.0
XFADE_SECONDS = 0.7
FPS = 30
CRF = 18
AUDIO_FADE_SECONDS = 1.5   # fade-out on the optional soundtrack's last seconds
AUDIO_BITRATE = "192k"


# ---------------------------------------------------------------------------
# Output-path convention
# ---------------------------------------------------------------------------
def build_output_paths(output_base_name):
    """Return (output_dir, pdf_path, mp4_path) for outputs/<base>/<base>.{pdf,mp4}.

    The base name is reduced to a bare filename (no traversal) and the folder is created.
    """
    # reason: None (the render_post_package default) must fall through to the theme's base
    # name, not stringify to "None".
    base = os.path.basename(str(output_base_name or "")).strip()
    if not base or base in (".", ".."):
        base = THEME.default_output_base
    try:
        os.mkdir(OUTPUT_ROOT)
    except FileExistsError:
        pass
    # reason: never overwrite a previous export that used the same base name — claim the first
    # free outputs/<base>[-N]/ so repeat/concurrent runs can't clobber each other's deliverables.
    # Relies on mkdir's atomic FileExistsError (not os.path.exists, which callers/tests monkeypatch).
    name, n = base, 2
    while True:
        out_dir = os.path.join(OUTPUT_ROOT, name)
        try:
            os.mkdir(out_dir)
            break
        except FileExistsError:
            name, n = f"{base}-{n}", n + 1
    return out_dir, os.path.join(out_dir, name + ".pdf"), os.path.join(out_dir, name + ".mp4")


# ---------------------------------------------------------------------------
# Robust asset loaders
# ---------------------------------------------------------------------------
def _font(path, size):
    # reason: never hard-fail on a missing/unreadable font — degrade to Pillow's default.
    try:
        return ImageFont.truetype(path, size)
    except (IOError, OSError):
        return ImageFont.load_default()


def _logo_content():
    """Load the logo cropped to its ink bbox (RGBA), or None if unavailable.

    reason: the source PNG carries large transparent margins (~766px sides, ~710px
    top/bottom). Cropping to the visible ink first makes every downstream scale/placement
    operate on the mark itself, matching the reference where the ink — not the padded
    canvas — sets the rendered height and origin.
    """
    if not os.path.exists(LOGO_PATH):
        return None
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
    except (IOError, OSError):
        return None
    bbox = logo.split()[3].getbbox()
    return logo.crop(bbox) if bbox else logo


def load_logo():
    """Header mark: visible ink scaled to LOGO_HEIGHT so its top-left lands at (60, 52),
    matching the reference (measured ~96px ink at pad 60, 52)."""
    logo = _logo_content()
    if logo is None:
        return None
    ratio = LOGO_HEIGHT / logo.height
    return logo.resize((max(1, int(logo.width * ratio)), LOGO_HEIGHT), Image.Resampling.LANCZOS)


def _load_logo_full():
    """Ink-cropped logo (RGBA) for the large centered end-card mark; None if unavailable."""
    return _logo_content()


# ---------------------------------------------------------------------------
# Image grading + crop (pure Pillow — no numpy dependency)
# ---------------------------------------------------------------------------
def _grade(img, exposure=1.0, contrast=1.0, saturation=1.0, sharpen=0.0,
           cool=0.0, denoise=False, lift_shadows=0.0):
    if denoise:
        img = img.filter(ImageFilter.MedianFilter(size=3))
    if exposure != 1.0:
        img = ImageEnhance.Brightness(img).enhance(exposure)
    if lift_shadows:
        lut = []
        for v in range(256):
            nv = v / 255.0
            nv = nv + lift_shadows * (1.0 - nv) * (1.0 - nv)
            lut.append(max(0, min(255, int(nv * 255))))
        img = img.point(lut * len(img.getbands()))
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if saturation != 1.0:
        img = ImageEnhance.Color(img).enhance(saturation)
    if cool:
        r, g, b = img.split()
        b = b.point(lambda v: min(255, int(v * (1 + cool))))
        r = r.point(lambda v: max(0, int(v * (1 - cool * 0.5))))
        img = Image.merge("RGB", (r, g, b))
    if sharpen:
        img = img.filter(ImageFilter.UnsharpMask(radius=2.2, percent=int(sharpen * 100), threshold=2))
    return img


def _crop(img, focus_x=0.5, focus_y=0.5, zoom=1.0):
    """Crop to the 4:5 canvas, biased toward a focus point, then resize."""
    iw, ih = img.size
    target = OUTPUT_WIDTH / OUTPUT_HEIGHT
    cw = ih * target
    if cw <= iw:
        cw, ch = cw / zoom, ih / zoom
    else:
        ch, cw = (iw / target) / zoom, iw / zoom
    cw, ch = min(cw, iw), min(ch, ih)
    x0 = (iw - cw) * focus_x
    y0 = (ih - ch) * focus_y
    img = img.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))
    return img.resize((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.Resampling.LANCZOS)


# ---------------------------------------------------------------------------
# Scrims + vignette (pure Pillow)
# ---------------------------------------------------------------------------
def _bottom_scrim(img, height=640, strength=0.9):
    grad = Image.new("L", (1, OUTPUT_HEIGHT), 0)
    start = OUTPUT_HEIGHT - height
    for y in range(start, OUTPUT_HEIGHT):
        t = (y - start) / height
        grad.putpixel((0, y), int(255 * strength * (t ** 1.6)))
    grad = grad.resize((OUTPUT_WIDTH, OUTPUT_HEIGHT))
    return Image.composite(Image.new("RGB", img.size, (0, 0, 0)), img, grad)


def _top_scrim(img, height=240, strength=0.45):
    grad = Image.new("L", (1, OUTPUT_HEIGHT), 0)
    for y in range(0, height):
        t = 1 - (y / height)
        grad.putpixel((0, y), int(255 * strength * (t ** 1.4)))
    grad = grad.resize((OUTPUT_WIDTH, OUTPUT_HEIGHT))
    return Image.composite(Image.new("RGB", img.size, (0, 0, 0)), img, grad)


def _vignette(img, strength=0.28):
    # radial_gradient: 0 at centre -> 255 at edges; scale it into a corner-darkening mask.
    mask = Image.radial_gradient("L").resize(img.size).point(lambda a: int(a * strength))
    return Image.composite(Image.new("RGB", img.size, (0, 0, 0)), img, mask)


# ---------------------------------------------------------------------------
# Text: clip-safe italic shear + optional letter-spacing (tracking)
# ---------------------------------------------------------------------------
def _render_line(text, font, fill, shear=0.0, tracking=0):
    """Render one line to a tight RGBA layer. Returns (layer, x_pad) where x_pad is the
    left padding added for the shear — composite at (x - x_pad) to land the visual left at x."""
    asc, desc = font.getmetrics()
    h = asc + desc + 8
    tmp = Image.new("RGBA", (OUTPUT_WIDTH * 2, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    if tracking:
        x = 0
        for ch in text:
            d.text((x, 0), ch, font=font, fill=fill)
            x += d.textlength(ch, font=font) + tracking
        used = x
    else:
        d.text((0, 0), text, font=font, fill=fill)
        used = d.textlength(text, font=font)
    tmp = tmp.crop((0, 0, max(1, int(used) + 6), h))
    if shear:
        w0, h0 = tmp.size
        xpad = int(math.ceil(h0 * shear)) + 2
        padded = Image.new("RGBA", (w0 + xpad * 2, h0), (0, 0, 0, 0))
        padded.paste(tmp, (xpad, 0))
        pw, ph = padded.size
        return padded.transform((pw, ph), Image.AFFINE, (1, shear, -shear * h0, 0, 1, 0),
                                resample=Image.BICUBIC), xpad
    return tmp, 0


def _text_w(text, font, tracking=0):
    d = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    if tracking:
        return int(sum(d.textlength(c, font=font) + tracking for c in text))
    return int(d.textlength(text, font=font))


def _split_two(words):
    """Split a word list into the two most balanced (by length) halves."""
    best = None
    for i in range(1, len(words)):
        left, right = " ".join(words[:i]), " ".join(words[i:])
        diff = abs(len(left) - len(right))
        if best is None or diff < best[0]:
            best = (diff, left, right)
    return best[1], best[2]


def _fit_headline(headline, max_w, base=92, min_size=56, step=6):
    """Resolve a headline (str -> auto-wrapped 1-2 lines, or list -> explicit lines) into a
    fitted (font, lines), shrinking the font until every line fits under max_w."""
    if isinstance(headline, (list, tuple)):
        lines = [str(x).upper().strip() for x in headline if str(x).strip()]
        if not lines:
            return _font(DISPLAY_FONT_PATH, base), []
        size = base
        while size > min_size:
            font = _font(DISPLAY_FONT_PATH, size)
            if all(_text_w(ln, font) <= max_w for ln in lines):
                return font, lines
            size -= step
        return _font(DISPLAY_FONT_PATH, min_size), lines

    text = str(headline).upper().strip()
    if not text:
        return _font(DISPLAY_FONT_PATH, base), []
    words = text.split()
    size = base
    while size >= min_size:
        font = _font(DISPLAY_FONT_PATH, size)
        if _text_w(text, font) <= max_w:
            return font, [text]
        if len(words) >= 2:
            l, r = _split_two(words)
            if _text_w(l, font) <= max_w and _text_w(r, font) <= max_w:
                return font, [l, r]
        size -= step
    font = _font(DISPLAY_FONT_PATH, min_size)
    return (font, list(_split_two(words))) if len(words) >= 2 else (font, [text])


# ---------------------------------------------------------------------------
# Brand furniture
# ---------------------------------------------------------------------------
def _draw_stamp(base, stamp, f1, f2):
    line1, line2 = stamp[0].upper(), stamp[1].upper()
    d = ImageDraw.Draw(base)
    rx, y = OUTPUT_WIDTH - 64, 64
    w1 = _text_w(line1, f1, tracking=3)
    d.ellipse([(rx - w1 - 22, y + 5), (rx - w1 - 10, y + 17)], fill=ACCENT_RED)
    layer1, _ = _render_line(line1, f1, STAMP_TEXT, tracking=3)
    base.alpha_composite(layer1, (rx - w1, y))
    w2 = _text_w(line2, f2, tracking=3)
    layer2, _ = _render_line(line2, f2, DIM_TEXT, tracking=3)
    base.alpha_composite(layer2, (rx - w2, y + 33))


def _draw_fader(base, fill_frac):
    """Right-edge vertical dashed tick strip; lit ticks scale with fill_frac (0..1)."""
    d = ImageDraw.Draw(base)
    x, top, bot, n = OUTPUT_WIDTH - 38, 430, 980, 16
    gap = (bot - top) / n
    th = gap * 0.52
    lit = int(round(fill_frac * n))
    for i in range(n):
        yy = bot - i * gap - th
        d.rectangle([(x, yy), (x + 10, yy + th)], fill=ACCENT_RED if i < lit else (40, 42, 46))
    d.rectangle([(x, bot + 4), (x + 10, bot + 16)], fill=ACCENT_RED)
    label, _ = _render_line("FADER", _font(BODY_FONT_PATH, 16), DIM_TEXT, tracking=4)
    base.alpha_composite(label.rotate(-90, expand=True), (x - 20, bot - 92))


def _draw_caption(base, kicker, headline, sub, f_kicker, f_sub):
    MARGIN = 60
    max_w = OUTPUT_WIDTH - MARGIN - 70  # right room clears the FADER column
    hfont, lines = _fit_headline(headline, max_w)
    kick_h = sum(f_kicker.getmetrics())
    head_h = sum(hfont.getmetrics())
    sub_h = sum(f_sub.getmetrics())
    rule_h, rule_gap, kick_gap, sub_gap = 6, 16, 20, 24
    total = rule_h + rule_gap + kick_h + kick_gap + len(lines) * head_h + sub_gap + sub_h
    y = OUTPUT_HEIGHT - 64 - total
    d = ImageDraw.Draw(base)
    d.rectangle([(MARGIN, y), (MARGIN + 54, y + rule_h)], fill=ACCENT_RED)
    y += rule_h + rule_gap
    if kicker:
        layer, _ = _render_line(kicker.upper(), f_kicker, ACCENT_RED, tracking=5)
        base.alpha_composite(layer, (MARGIN, y))
    y += kick_h + kick_gap
    for ln in lines:
        layer, xpad = _render_line(ln, hfont, PURE_WHITE, shear=SHEAR)
        base.alpha_composite(layer, (MARGIN - xpad, y))
        y += head_h
    y += sub_gap
    if sub:
        layer, _ = _render_line(sub, f_sub, SILVER_TEXT)
        base.alpha_composite(layer, (MARGIN, y))


def _draw_url(base, f_url):
    w = _text_w(CONTACT_URL, f_url)
    uh = sum(f_url.getmetrics())
    layer, _ = _render_line(CONTACT_URL, f_url, PURE_WHITE)
    base.alpha_composite(layer, (OUTPUT_WIDTH - 60 - w, OUTPUT_HEIGHT - 64 - uh))


# ---------------------------------------------------------------------------
# Slide + end-card composition
# ---------------------------------------------------------------------------
def _compose_slide(img, slide, idx, count, logo, stamp, enable_fader, fonts):
    """Grade/crop the photo, layer scrims, and stamp brand furniture. Returns RGB."""
    img = _grade(img, **{**DEFAULT_GRADE, **slide.get("grade", {})})
    img = _crop(img, **{**DEFAULT_CROP, **slide.get("crop", {})})
    graded = img.copy()  # clean (text-free) copy for the end-card background
    img = _top_scrim(img)
    img = _bottom_scrim(img)
    img = _vignette(img)
    base = img.convert("RGBA")
    if logo:
        base.alpha_composite(logo, (60, 52))  # measured reference logo origin
    else:
        ImageDraw.Draw(base).text((60, 60), THEME.brand_short, fill=PURE_WHITE, font=fonts["sub"])
    # Top-right location stamp on every slide: line1 from slide["location"], line2 from an
    # optional slide["tagline"] — each falling back to the event-level `stamp` tuple. Sourced
    # from the LOCATION field, never slide["sub"] (that is the bottom-left ethos line).
    location = slide.get("location")
    tagline = slide.get("tagline")
    line1 = location if location is not None else (stamp[0] if stamp else None)
    line2 = tagline if tagline is not None else (stamp[1] if stamp else "")
    if line1:
        _draw_stamp(base, (line1, line2), fonts["stamp1"], fonts["stamp2"])
    if enable_fader:
        frac = slide.get("scale_frac")
        if frac is None:
            frac = (idx + 1) / count if count else 1.0
        _draw_fader(base, frac)
    _draw_caption(base, slide.get("kicker", ""), slide.get("headline", ""),
                  slide.get("sub", ""), fonts["kicker"], fonts["sub"])
    _draw_url(base, fonts["url"])
    return base.convert("RGB"), graded


def _build_endcard(bg_img, logo_full, footer, fonts):
    img = _grade(bg_img, exposure=0.92, contrast=1.05, saturation=0.85)
    img = img.filter(ImageFilter.GaussianBlur(30))
    img = ImageEnhance.Brightness(img).enhance(0.40)
    img = _vignette(img, 0.45)
    base = img.convert("RGBA")
    d = ImageDraw.Draw(base)
    cx = OUTPUT_WIDTH // 2
    if logo_full:
        logo_h = 230
        scale = logo_h / logo_full.height
        lw = int(logo_full.width * scale)
        logo = logo_full.resize((lw, logo_h), Image.Resampling.LANCZOS)
        logo_y = 430
        base.alpha_composite(logo, (cx - lw // 2, logo_y))
        rule_y = logo_y + logo_h + 24
    else:
        layer, xpad = _render_line(THEME.brand_full, fonts["display"], PURE_WHITE, shear=SHEAR)
        base.alpha_composite(layer, (cx - layer.width // 2 - xpad, 470))
        rule_y = 560
    d.rectangle([(cx - 75, rule_y), (cx + 75, rule_y + 6)], fill=ACCENT_RED)
    ty = rule_y + 38
    for i, tag in enumerate((TAGLINE_1, TAGLINE_2)):
        w = _text_w(tag, fonts["tag"], tracking=3)
        layer, _ = _render_line(tag, fonts["tag"], (205, 209, 215), tracking=3)
        base.alpha_composite(layer, (cx - w // 2, ty + i * 40))
    cy = ty + 120
    # CHANGED: URL and phone line are stacked + centred (phone line may carry multiple numbers).
    for i, line in enumerate((CONTACT_URL, CONTACT_PHONE)):
        w = _text_w(line, fonts["contact"], tracking=1)
        layer, _ = _render_line(line, fonts["contact"], PURE_WHITE, tracking=1)
        base.alpha_composite(layer, (cx - w // 2, cy + i * 48))
    if footer:
        fw = _text_w(footer.upper(), fonts["foot"], tracking=6)
        layer, _ = _render_line(footer.upper(), fonts["foot"], (90, 94, 100), tracking=6)
        base.alpha_composite(layer, (cx - fw // 2, OUTPUT_HEIGHT - 150))
    return base.convert("RGB")


# ---------------------------------------------------------------------------
# Deliverable assembly (PDF + MP4 from the SAME rendered frames — kept consistent)
# ---------------------------------------------------------------------------
def _build_pdf(frame_paths, out_path):
    images = [Image.open(p).convert("RGB") for p in frame_paths]
    images[0].save(out_path, "PDF", save_all=True, append_images=images[1:], resolution=300.0)


def _video_duration(n, hold=HOLD_SECONDS, xfade=XFADE_SECONDS):
    """Total length of the xfade chain: every crossfade overlaps two holds."""
    return round(n * hold - max(n - 1, 0) * xfade, 3)


def _build_mp4(frame_paths, out_path, hold=HOLD_SECONDS, xfade=XFADE_SECONDS, fps=FPS, crf=CRF,
               audio_path=None):
    """Returns True if the MP4 was produced, False otherwise (ffmpeg missing or failed).

    audio_path: optional soundtrack (any ffmpeg-readable audio, e.g. MP3). It is looped if shorter
    than the video, trimmed to the video's exact length, and faded out over the last seconds."""
    if shutil.which("ffmpeg") is None:
        print("System Notice: ffmpeg not found on PATH; MP4 not produced.")
        return False
    n = len(frame_paths)
    inputs = []
    for p in frame_paths:
        inputs += ["-loop", "1", "-t", str(hold), "-i", p]
    parts = [f"[{i}:v]format=yuv420p,fps={fps},setsar=1[v{i}]" for i in range(n)]
    if n == 1:
        filter_complex = f"[0:v]format=yuv420p,fps={fps},setsar=1[vout]"
    else:
        prev, offset = "v0", 0.0
        for i in range(1, n):
            offset += hold - xfade
            label = f"x{i}" if i < n - 1 else "vout"
            parts.append(f"[{prev}][v{i}]xfade=transition=fade:duration={xfade}:"
                         f"offset={round(offset, 3)}[{label}]")
            prev = label
        filter_complex = ";".join(parts)
    audio_args = ["-an"]
    if audio_path:
        duration = _video_duration(n, hold, xfade)
        fade = min(AUDIO_FADE_SECONDS, duration / 2)
        # -stream_loop -1 repeats a short track; atrim cuts it to the video length exactly.
        inputs += ["-stream_loop", "-1", "-i", audio_path]
        filter_complex += (f";[{n}:a]atrim=0:{duration},asetpts=PTS-STARTPTS,"
                           f"afade=t=out:st={round(duration - fade, 3)}:d={round(fade, 3)}[aout]")
        audio_args = ["-map", "[aout]", "-c:a", "aac", "-b:a", AUDIO_BITRATE]
    cmd = ["ffmpeg", "-y", "-loglevel", "error"] + inputs + [
        "-filter_complex", filter_complex, "-map", "[vout]",
        "-c:v", "libx264", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-r", str(fps),
    ] + audio_args + [out_path]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except FileNotFoundError:
        print("System Notice: ffmpeg not found on PATH; MP4 not produced.")
        return False
    except subprocess.CalledProcessError as exc:
        print(f"System Notice: ffmpeg render failed (exit {exc.returncode}); MP4 not produced.")
        return False
    return True


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def render_post_package(slides_dataset, output_base_name=None,
                        stamp=None, footer=None, enable_fader=True, audio_path=None):
    """Render a slide deck to outputs/<base>/<base>.pdf and .mp4.

    slides_dataset: list of {path, kicker, headline, sub} dicts (each may optionally carry
    a "grade" or "crop" override dict). `stamp` is an optional (line1, line2) top-right
    corner stamp; `footer` an optional end-card footer — both omitted when not provided.
    `audio_path` is an optional soundtrack fitted to the video length (see _build_mp4).
    Returns {"mp4", "pdf", "audio"} — absolute paths ("mp4" is None when ffmpeg is missing or
    failed — R9: never report a deliverable that was not written) and "audio", True only when the
    soundtrack made it into the MP4 — or None if no slide image was usable.
    """
    out_dir, pdf_path, mp4_path = build_output_paths(output_base_name)
    logo = load_logo()
    logo_full = _load_logo_full()
    fonts = {
        "display": _font(DISPLAY_FONT_PATH, 92),
        "kicker": _font(DISPLAY_FONT_PATH, 30),
        "sub": _font(BODY_FONT_PATH, 30),
        "url": _font(DISPLAY_FONT_PATH, 30),
        "stamp1": _font(DISPLAY_FONT_PATH, 24),
        "stamp2": _font(BODY_FONT_PATH, 15),
        "tag": _font(BODY_FONT_PATH, 26),
        "contact": _font(DISPLAY_FONT_PATH, 34),
        "foot": _font(BODY_FONT_PATH, 22),
    }
    count = len(slides_dataset)

    # reason: temp frames live in an auto-deleted dir (not the project root), so a crash
    # mid-render never leaves orphaned artifacts and deliverables stay isolated.
    with tempfile.TemporaryDirectory(prefix="campaign_render_") as tmpdir:
        frame_paths = []
        last_bg = None
        for idx, slide in enumerate(slides_dataset):
            path = slide.get("path")
            if not path or not os.path.exists(path):
                continue
            try:
                img = Image.open(path).convert("RGB")
            except Exception as e:
                # reason: a corrupt-but-present upload must not 500 the whole render — skip it
                # (parity with the analyze path, which already tolerates unreadable images).
                print(f"[compositor] skipping unreadable image {path}: {e}")
                continue
            frame, last_bg = _compose_slide(img, slide, idx, count, logo, stamp, enable_fader, fonts)
            fp = os.path.join(tmpdir, f"slide_{idx:03d}.jpg")
            frame.save(fp, "JPEG", quality=95)
            frame_paths.append(fp)

        if not frame_paths:
            return None

        endcard = _build_endcard(last_bg, logo_full, footer, fonts)
        efp = os.path.join(tmpdir, "slide_end.jpg")
        endcard.save(efp, "JPEG", quality=95)
        frame_paths.append(efp)

        _build_pdf(frame_paths, pdf_path)
        audio_ok = False
        if audio_path and os.path.exists(audio_path):
            audio_ok = mp4_ok = _build_mp4(frame_paths, mp4_path, audio_path=audio_path)
            if not mp4_ok:
                # reason: a bad/undecodable audio file must not cost the operator the video —
                # fall back to the silent MP4 and report the soundtrack as dropped.
                print("System Notice: soundtrack could not be muxed; retrying MP4 without audio.")
                mp4_ok = _build_mp4(frame_paths, mp4_path)
        else:
            mp4_ok = _build_mp4(frame_paths, mp4_path)

    # reason: R9 — the mp4 path was previously returned even when _build_mp4 bailed
    # (ffmpeg missing/failed), so clients received a path to a file that doesn't exist.
    return {"mp4": mp4_path if mp4_ok else None, "pdf": pdf_path, "audio": audio_ok}
