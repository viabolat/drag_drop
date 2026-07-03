"""
EVENT CONFIG — Texas "FROM THIS SEAT"

This is the per-event source of truth. To make a new post, copy this file to
events/<yourevent>.py and edit the values below. The engine never changes.

A config defines:
  EVENT      : short id (used for output filenames)
  STAMP      : (line1, line2) top-right corner stamp  -> "LOCATION" / "TAGLINE"
  FOOTER     : end-card bottom footer text
  GRADING    : default grade applied to every slide (override per slide if needed)
  ENDCARD_BG : filename (in inputs/<event>/) used as the blurred end-card background
  FADER      : whether to draw the right-edge FADER strip (see brief caution)
  SLIDES     : ordered list of slide dicts

Each SLIDE dict:
  src        : filename inside inputs/<event>/
  kicker     : red label (letter-spaced)
  head       : list of headline lines (1-2), white condensed italic
  sub        : silver ethos sub-line
  crop       : dict(focus_y, focus_x, zoom) for the 4:5 crop
  grade      : optional dict overriding GRADING for this slide
  scale_frac : 0..1 FADER fill for this slide
  top_strength : top-scrim strength (raise for bright frames)
"""

EVENT = "Texas_FromThisSeat"
STAMP = ("TEXAS", "EVERYTHING'S BIGGER")
FOOTER = "TEXAS & BEYOND"
FADER = True

# Dark / console-forward grading: lift exposure, add contrast, slight cool.
GRADING = dict(exposure=1.12, contrast=1.10, saturation=1.12, sharpen=0.5,
               lift_shadows=0.06, cool=0.03)

ENDCARD_BG = "three_screens.png"

SLIDES = [
    dict(
        src="stage_square.png",
        kicker="BEFORE THE DOORS",
        head=["QUIET IS THE", "WORK"],
        sub="The biggest rooms start dead silent.",
        crop=dict(focus_y=0.30, focus_x=0.5, zoom=1.02),
        grade=dict(exposure=1.18, contrast=1.06, saturation=1.05, denoise=True,
                   sharpen=0.45, lift_shadows=0.10, cool=0.04),
        scale_frac=0.18, top_strength=0.62,
    ),
    dict(
        src="small_big2.png",
        kicker="THE SEAT",
        head=["WHERE THE", "SHOW LIVES"],
        sub="Everything scales up. The desk stays still.",
        crop=dict(focus_y=0.46, focus_x=0.5, zoom=1.0),
        grade=dict(exposure=1.12, contrast=1.10, saturation=1.12,
                   sharpen=0.5, lift_shadows=0.06, cool=0.05),
        scale_frac=0.5, top_strength=0.5,
    ),
    dict(
        src="stage_oval.png",
        kicker="DOORS OPEN",
        head=["THE ROOM", "TURNS ON"],
        sub="Hundreds of voices. One clean signal.",
        crop=dict(focus_y=0.40, focus_x=0.5, zoom=1.0),
        grade=dict(exposure=1.14, contrast=1.10, saturation=1.18,
                   sharpen=0.55, lift_shadows=0.08, cool=0.02),
        scale_frac=0.74, top_strength=0.5,
    ),
    dict(
        src="three_screens.png",
        kicker="PEAK",
        head=["AND THE", "MOMENT LANDS"],
        sub="Everyone feels it. No one sees us.",
        crop=dict(focus_y=0.40, focus_x=0.5, zoom=1.0),
        grade=dict(exposure=1.10, contrast=1.12, saturation=1.14,
                   sharpen=0.5, lift_shadows=0.05, cool=0.0),
        scale_frac=1.0, top_strength=0.5,
    ),
]

# MP4 timing (locked spec defaults; brief floor is ~20-30s — raise HOLD to ~4.9s
# or add a slide if you need to land in that range. 4 slides + endcard @4.0s = 17.2s).
HOLD = 4.0
XFADE = 0.7
