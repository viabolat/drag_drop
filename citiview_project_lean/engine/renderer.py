#!/usr/bin/env python3
"""
CitiView AV — slide rendering engine (portable).

This module is the LOCKED engine: brand furniture, grading, italic-shear text
(clip-safe), scrims, FADER strip, caption layout, and end card. It changes only
when the house style itself changes — never per event.

Per-event content lives in events/<name>.py (see events/texas.py for the schema).
Run a build with:  python build.py <event>

All paths resolve relative to the project root, so the folder is portable:
drop it anywhere, keep the structure, and it runs.
"""
import os
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

# ---------------------------------------------------------------------------
# Path resolution — everything is relative to the project root (parent of engine/)
# ---------------------------------------------------------------------------
ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(ENGINE_DIR)
ASSETS = os.path.join(ROOT, "assets")
FONTS = os.path.join(ASSETS, "fonts")
INPUTS = os.path.join(ROOT, "inputs")
OUTPUTS = os.path.join(ROOT, "outputs")
LOGO_PATH = os.path.join(ASSETS, "logo_cn_white.png")

W, H = 1080, 1350

# ---- Brand palette ----
RED = (225, 29, 42)      # #e11d2a primary
RED_BR = (255, 62, 74)   # #ff3e4a bright accent
WHITE = (255, 255, 255)
SILVER = (176, 180, 186)
DIM = (120, 124, 130)
BLACK = (0, 0, 0)


# ---- Fonts ----
def F(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)


f_stamp = F("BarlowCondensed-SemiBold.ttf", 26)
f_stamp_sm = F("BarlowCondensed-Medium.ttf", 21)
f_kicker = F("BarlowCondensed-Bold.ttf", 30)
f_head = F("Oswald-Bold.ttf", 96)
f_sub = F("Barlow-Medium.ttf", 34)
f_url = F("BarlowCondensed-SemiBold.ttf", 30)
f_scale = F("BarlowCondensed-Medium.ttf", 16)

# ---- Extracted brand logo (CN mark + CITIVIEW / AUDIO VISUAL, knockout white) ----
LOGO_FULL = Image.open(LOGO_PATH).convert("RGBA")

# ---- Contact / tagline (brand constants) ----
TAGLINE_1 = "FULL EVENT PRODUCTION \u00b7 LIGHTING \u00b7 STAGING"
TAGLINE_2 = "SOUND \u00b7 VIDEO \u00b7 STREAMING"
CONTACT_URL = "CitiViewAV.com"
CONTACT_PHONE = "212-632-5196"


# ---------------------------------------------------------------------------
# Image grading
# ---------------------------------------------------------------------------
def grade(img, exposure=1.0, contrast=1.0, saturation=1.0, denoise=False,
          sharpen=0.0, cool=0.0, lift_shadows=0.0):
    if denoise:
        img = img.filter(ImageFilter.MedianFilter(size=3))
    if exposure != 1.0:
        img = ImageEnhance.Brightness(img).enhance(exposure)
    if lift_shadows:
        arr = np.asarray(img).astype(np.float32) / 255.0
        arr = arr + lift_shadows * (1.0 - arr) * (1.0 - arr)
        img = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if saturation != 1.0:
        img = ImageEnhance.Color(img).enhance(saturation)
    if cool:
        arr = np.asarray(img).astype(np.float32)
        arr[..., 2] = np.clip(arr[..., 2] * (1 + cool), 0, 255)
        arr[..., 0] = np.clip(arr[..., 0] * (1 - cool * 0.5), 0, 255)
        img = Image.fromarray(arr.astype(np.uint8))
    if sharpen:
        img = img.filter(ImageFilter.UnsharpMask(radius=2.2, percent=int(sharpen * 100), threshold=2))
    return img


def crop_to_45(img, focus_y=0.5, focus_x=0.5, zoom=1.0):
    """Crop any image to 4:5 portrait, biasing toward a focus point."""
    iw, ih = img.size
    target = W / H  # 0.8
    cw = ih * target
    if cw <= iw:
        cw = cw / zoom
        ch = ih / zoom
    else:
        ch = (iw / target) / zoom
        cw = iw / zoom
    cw, ch = min(cw, iw), min(ch, ih)
    x0 = (iw - cw) * focus_x
    y0 = (ih - ch) * focus_y
    img = img.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))
    return img.resize((W, H), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Text with clip-safe italic shear
# ---------------------------------------------------------------------------
def shear_italic(text_img, shear=0.16):
    """Forward (top-leans-right) italic shear with two-sided padding so no
    glyph pixel ever falls outside the canvas."""
    w, h = text_img.size
    xshift = int(math.ceil(h * shear)) + 2
    padded = Image.new("RGBA", (w + xshift * 2, h), (0, 0, 0, 0))
    padded.paste(text_img, (xshift, 0))
    pw, ph = padded.size
    return padded.transform((pw, ph), Image.AFFINE,
                            (1, shear, -shear * h, 0, 1, 0),
                            resample=Image.BICUBIC)


def draw_text_sheared(base, xy, text, font, fill, shear=0.16, tracking=0):
    """Draw sheared/tracked text onto base (RGBA). Visual left edge lands at xy[0]."""
    asc, desc = font.getmetrics()
    canvas_h = asc + desc + 6
    tmp = Image.new("RGBA", (W * 2, canvas_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    if tracking:
        x = 0
        for ch in text:
            d.text((x, 0), ch, font=font, fill=fill)
            bbox = d.textbbox((0, 0), ch, font=font)
            x += (bbox[2] - bbox[0]) + tracking
        used_w = x
    else:
        d.text((0, 0), text, font=font, fill=fill)
        bbox = d.textbbox((0, 0), text, font=font)
        used_w = bbox[2] - bbox[0]
    tmp = tmp.crop((0, 0, max(1, used_w + 4), canvas_h))
    if shear:
        xshift = int(math.ceil(canvas_h * shear)) + 2
        tmp = shear_italic(tmp, shear)
        base.alpha_composite(tmp, (int(xy[0]) - xshift, int(xy[1])))
    else:
        base.alpha_composite(tmp, (int(xy[0]), int(xy[1])))
    return used_w


def text_width(text, font, tracking=0):
    tmp = Image.new("RGBA", (10, 10))
    d = ImageDraw.Draw(tmp)
    if tracking:
        w = 0
        for ch in text:
            bbox = d.textbbox((0, 0), ch, font=font)
            w += (bbox[2] - bbox[0]) + tracking
        return w
    bbox = d.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


# ---------------------------------------------------------------------------
# Scrims & vignette
# ---------------------------------------------------------------------------
def bottom_scrim(img, height=620, strength=0.92):
    grad = Image.new("L", (1, H), 0)
    for y in range(H):
        if y < H - height:
            a = 0
        else:
            t = (y - (H - height)) / height
            a = int(255 * strength * (t ** 1.6))
        grad.putpixel((0, y), a)
    grad = grad.resize((W, H))
    return Image.composite(Image.new("RGB", (W, H), BLACK), img, grad)


def top_scrim(img, height=240, strength=0.55):
    grad = Image.new("L", (1, H), 0)
    for y in range(H):
        if y > height:
            a = 0
        else:
            t = 1 - (y / height)
            a = int(255 * strength * (t ** 1.4))
        grad.putpixel((0, y), a)
    grad = grad.resize((W, H))
    return Image.composite(Image.new("RGB", (W, H), BLACK), img, grad)


def caption_scrim(img, width=820, height=640, strength=0.72):
    y0 = H - height
    ys = np.arange(H)
    vy = np.clip((ys - y0) / height, 0, 1) ** 1.05
    xs = np.arange(W)
    hx = np.clip(1 - (xs - width * 0.55) / (width * 0.55), 0, 1)
    hx = np.clip(hx, 0, 1) ** 0.9
    field = (vy[:, None] * hx[None, :]) * (255 * strength)
    mask = Image.fromarray(field.astype(np.uint8)).filter(ImageFilter.GaussianBlur(50))
    return Image.composite(Image.new("RGB", (W, H), BLACK), img, mask)


def vignette(img, strength=0.32):
    x = np.linspace(-1, 1, W)[None, :]
    y = np.linspace(-1, 1, H)[:, None]
    r = np.sqrt(x ** 2 + y ** 2)
    mask = np.clip(1 - strength * (r ** 2.2), 0, 1)
    arr = np.asarray(img).astype(np.float32) * mask[..., None]
    return Image.fromarray(arr.astype(np.uint8))


# ---------------------------------------------------------------------------
# Brand furniture
# ---------------------------------------------------------------------------
def draw_logo(base):
    target_h = 96
    scale = target_h / LOGO_FULL.height
    logo = LOGO_FULL.resize((int(LOGO_FULL.width * scale), target_h), Image.LANCZOS)
    base.alpha_composite(logo, (60, 52))


def draw_stamp(base, line1, line2):
    d = ImageDraw.Draw(base)
    rx = W - 64
    w1 = text_width(line1, f_stamp, tracking=3)
    y = 64
    d.ellipse([(rx - w1 - 22, y + 5), (rx - w1 - 10, y + 17)], fill=RED)
    draw_text_sheared(base, (rx - w1, y), line1, f_stamp, (210, 214, 220, 255), shear=0, tracking=3)
    w2 = text_width(line2, f_stamp_sm, tracking=3)
    draw_text_sheared(base, (rx - w2, y + 34), line2, f_stamp_sm, DIM + (255,), shear=0, tracking=3)


def draw_scale_strip(base, fill_frac, label="FADER"):
    """Right-edge vertical dashed tick strip. fill_frac (0..1) sets lit ticks.
    NOTE: this device reads as meaningful in console-forward contexts; treat as
    neutral brand furniture elsewhere (see brief). Set enable_fader_strip=False
    in an event config to omit it."""
    d = ImageDraw.Draw(base)
    x = W - 38
    top, bot, n = 430, 980, 16
    gap = (bot - top) / n
    th = gap * 0.52
    lit = int(round(fill_frac * n))
    for i in range(n):
        yy = bot - i * gap - th
        if i < lit:
            c = RED if i < lit - 1 else RED_BR
        else:
            c = (40, 42, 46)
        d.rectangle([(x, yy), (x + 10, yy + th)], fill=c)
    d.rectangle([(x, bot + 4), (x + 10, bot + 16)], fill=RED)
    lab = Image.new("RGBA", (text_width(label, f_scale, 4) + 8, 24), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lab)
    xx = 0
    for ch in label:
        ld.text((xx, 2), ch, font=f_scale, fill=DIM + (255,))
        bb = ld.textbbox((0, 0), ch, font=f_scale)
        xx += (bb[2] - bb[0]) + 4
    lab = lab.rotate(-90, expand=True)
    base.alpha_composite(lab, (x - 20, bot - 90))


def caption_block(base, kicker, headline_lines, sub):
    """Caption rendered on its own padded layer so sheared glyphs never clip."""
    PAD = 60
    layer_h = 720
    layer = Image.new("RGBA", (W, layer_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    line_h = 90
    head_h = line_h * len(headline_lines)
    kick_h, gap_kick_head, gap_head_sub, sub_h, bottom_margin = 38, 26, 30, 44, 14
    total = kick_h + gap_kick_head + head_h + gap_head_sub + sub_h
    y = layer_h - bottom_margin - total
    d.rectangle([(PAD, y - 16), (PAD + 54, y - 11)], fill=RED)
    draw_text_sheared(layer, (PAD, y), kicker, f_kicker, RED + (255,), shear=0, tracking=5)
    y += kick_h + gap_kick_head
    for ln in headline_lines:
        draw_text_sheared(layer, (PAD, y), ln, f_head, WHITE + (255,), shear=0.14, tracking=0)
        y += line_h
    y += gap_head_sub
    draw_text_sheared(layer, (PAD, y), sub, f_sub, SILVER + (255,), shear=0, tracking=0)
    base.alpha_composite(layer, (12, H - layer_h - 8))


def draw_url(base, text=CONTACT_URL):
    w = text_width(text, f_url, tracking=1)
    draw_text_sheared(base, (W - 64 - w, H - 70), text, f_url, WHITE + (255,), shear=0, tracking=1)


# ---------------------------------------------------------------------------
# Slide + end card builders
# ---------------------------------------------------------------------------
def build_slide(src_path, crop_kw, grade_kw, kicker, head_lines, sub,
                scale_frac, stamp, top_strength=0.5, enable_fader_strip=True, out=None):
    img = Image.open(src_path).convert("RGB")
    img = grade(img, **grade_kw)
    img = crop_to_45(img, **crop_kw)
    img = top_scrim(img, height=250, strength=top_strength)
    img = bottom_scrim(img, height=640, strength=0.93)
    img = caption_scrim(img, width=820, height=640, strength=0.72)
    img = vignette(img, strength=0.30)
    base = img.convert("RGBA")
    draw_logo(base)
    draw_stamp(base, stamp[0], stamp[1])
    if enable_fader_strip:
        draw_scale_strip(base, scale_frac)
    caption_block(base, kicker, head_lines, sub)
    draw_url(base)
    base = base.convert("RGB")
    if out:
        base.save(out, quality=95)
    return base


def build_endcard(bg_src_path, footer_text, out=None):
    img = Image.open(bg_src_path).convert("RGB")
    img = grade(img, exposure=0.93, saturation=0.85, contrast=1.05)
    img = crop_to_45(img, focus_y=0.45, focus_x=0.5, zoom=1.08)
    img = img.filter(ImageFilter.GaussianBlur(30))
    arr = (np.asarray(img).astype(np.float32) * 0.40).astype(np.uint8)
    img = vignette(Image.fromarray(arr), strength=0.45)
    base = img.convert("RGBA")
    d = ImageDraw.Draw(base)
    cx = W // 2
    logo_h = 260
    scale = logo_h / LOGO_FULL.height
    lw = int(LOGO_FULL.width * scale)
    logo = LOGO_FULL.resize((lw, logo_h), Image.LANCZOS)
    logo_y = 430
    base.alpha_composite(logo, (cx - lw // 2, logo_y))
    rule_y = logo_y + logo_h + 26
    d.rectangle([(cx - 75, rule_y), (cx + 75, rule_y + 6)], fill=RED)
    f_tag = F("BarlowCondensed-SemiBold.ttf", 31)
    ty = rule_y + 40
    for i, t in enumerate([TAGLINE_1, TAGLINE_2]):
        tw = text_width(t, f_tag, tracking=3)
        draw_text_sheared(base, (cx - tw // 2, ty + i * 44), t, f_tag, (205, 209, 215, 255), shear=0, tracking=3)
    f_con = F("BarlowCondensed-Bold.ttf", 38)
    cwid = text_width(CONTACT_URL, f_con, tracking=1)
    pwid = text_width(CONTACT_PHONE, f_con, tracking=1)
    dotw = 40
    sx = cx - (cwid + dotw + pwid) // 2
    cy2 = ty + 130
    w = draw_text_sheared(base, (sx, cy2), CONTACT_URL, f_con, WHITE + (255,), shear=0, tracking=1)
    d.ellipse([(sx + w + 14, cy2 + 22), (sx + w + 22, cy2 + 30)], fill=RED)
    draw_text_sheared(base, (sx + w + dotw, cy2), CONTACT_PHONE, f_con, WHITE + (255,), shear=0, tracking=1)
    f_foot = F("BarlowCondensed-Medium.ttf", 24)
    fw = text_width(footer_text, f_foot, tracking=6)
    draw_text_sheared(base, (cx - fw // 2, H - 150), footer_text, f_foot, (90, 94, 100, 255), shear=0, tracking=6)
    base = base.convert("RGB")
    if out:
        base.save(out, quality=95)
    return base
