# CitiView AV — Social Content Production

Source-of-truth project for CitiView AV behind-the-scenes social posts.
Each event produces **exactly two deliverables**: a 4:5 PDF carousel and a
silent 4:5 MP4, both 1080×1350.

## Quick start

```bash
# 1. install dependencies (Python 3.9+ and ffmpeg on PATH)
pip install -r requirements.txt
#    ffmpeg: macOS `brew install ffmpeg` | Ubuntu `apt install ffmpeg`

# 2. build an event
python build.py texas
python build.py vienna
```

Outputs land in `outputs/`:
```
CitiViewAV_<EVENT>_4x5.pdf
CitiViewAV_<EVENT>.mp4
```
Individual slides are rendered to a temp dir and are **never** delivered
(per brief: only the PDF + MP4).

## Add a new event

1. Put the event's photos in `inputs/<event>/`.
2. Copy `events/texas.py` to `events/<event>.py` and edit the values
   (stamp, footer, grading, slide list, copy). The docstring at the top of
   that file documents every field.
3. Run `python build.py <event>`.

That's it — the engine never changes. A new post is a ~30-line config.

## Architecture

```
build.py              # runner: python build.py <event>
engine/
  renderer.py         # LOCKED engine: grading, clip-safe italic text,
                      #   scrims, FADER strip, caption layout, end card
  assemble.py         # PDF + MP4 (ffmpeg xfade) assembly
events/
  texas.py            # per-event config (schema reference)
  vienna.py           # per-event config
assets/
  logo_cn_white.png   # CN lockup, knockout white (extracted)
  fonts/              # Oswald + Barlow / Barlow Condensed
inputs/<event>/       # source photos per event
outputs/              # the two deliverables per event
```

**Why this split:** the engine is the part that must stay identical across every
post (brand furniture, the glyph-clip fix, spacing). The config is the part that
changes every time (photos, copy, grading). Keeping them separate means the house
style can't drift by accident and a new event never touches rendering code.

## House style (locked)

- Logo: CN mark + CITIVIEW / AUDIO VISUAL lockup, knockout white (top-left;
  centered on end card). The old red-slash wordmark is retired.
- Headlines: Oswald Bold, condensed, forward italic shear (clip-safe).
- Palette: black / silver + red (#e11d2a primary, #ff3e4a accent).
- Corner stamp: `LOCATION` / `TAGLINE`, top-right.
- Caption: kicker (red) → headline (white) → sub (silver), bottom-left,
  on a localized scrim so the kicker always reads.

## Grading logic

- **Dark / console-forward events** → lift exposure, add contrast, slight cool
  (see `events/texas.py`).
- **Bright / daylit events** → pull exposure DOWN, no cool shift, keep airy
  (see `events/vienna.py`).

## MP4 spec (locked)

1080×1350, 30fps, silent, H.264/yuv420p, CRF 17, +faststart.
Static holds (default 4.0s) + 0.7s crossfades, no Ken Burns.
Total = n·hold − (n−1)·xfade.

**Note on duration:** 4 slides + end card at 4.0s holds = 17.2s, which is under
the original brief's ~20–30s floor. To land in range, raise `HOLD` to ~4.9s in
the event config, or add a slide. `build.py` prints a warning when a build comes
in under 20s.

## Notes / cautions carried from the brief

- **Frame discipline:** near-identical frames hurt feed performance; prefer a
  tighter, narratively distinct cut and let copy differentiate similar shots.
- **FADER strip:** meaningful in console-forward contexts, decorative in
  lounge/ambient ones. Set `FADER = False` in a config to omit it.
- **Organizer branding:** when event-organizer logos appear in source photos
  (e.g. the Vienna robot), that's a positioning decision — flag before posting.
- **Logo asset** is a raster extraction from `citiview-behind-the-build.pdf`.
  It's crisp at the sizes used here; if a vector original exists, drop it in as
  `assets/logo_cn_white.png` for infinite scaling.

## Optional add-ons (not built by default)

- 9:16 Reels/Stories cut (1080×1920) — recommend branded letterbox bands over
  re-cropping, to preserve the tight compositions.
- Royalty-free cinematic music bed for the MP4.
