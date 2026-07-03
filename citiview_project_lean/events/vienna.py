"""
EVENT CONFIG — Vienna "Global Summit 2026"

Daylit event: note the grading is the INVERSE of Texas — exposure pulled DOWN,
no cool shift, to keep bright rooms airy rather than forcing them dark.
"""

EVENT = "Vienna_GlobalSummit"
STAMP = ("VIENNA", "GLOBAL SUMMIT 2026")
FOOTER = "VIENNA \u00b7 GLOBAL SUMMIT 2026"
FADER = True  # consider False for pure lounge sets (device is decorative here)

# Bright / daylit grading: pull exposure down, no cool shift, preserve warmth.
GRADING = dict(exposure=0.96, contrast=1.10, saturation=1.06, sharpen=0.4, cool=0.0)

ENDCARD_BG = "v_live.png"

SLIDES = [
    dict(
        src="v_robot.png",
        kicker="OUR PRESENCE",
        head=["WE SHOWED UP", "IN VIENNA"],
        sub="Where the industry's future gets built.",
        crop=dict(focus_y=0.42, focus_x=0.5, zoom=1.0),
        grade=dict(exposure=1.02, contrast=1.08, saturation=1.10, sharpen=0.4, cool=0.0),
        scale_frac=0.25, top_strength=0.45,
    ),
    dict(
        src="v_build.png",
        kicker="THE BUILD",
        head=["AN EMPTY ROOM,", "FOR NOW"],
        sub="Hours before, it's just light and intent.",
        crop=dict(focus_y=0.40, focus_x=0.5, zoom=1.0),
        grade=dict(exposure=0.96, contrast=1.10, saturation=1.06, sharpen=0.4, cool=0.0),
        scale_frac=0.5, top_strength=0.5,
    ),
    dict(
        src="v_live.png",
        kicker="SHOWTIME",
        head=["THEN IT GOES", "TO WORK"],
        sub="The room disappears. The message lands.",
        crop=dict(focus_y=0.42, focus_x=0.5, zoom=1.0),
        grade=dict(exposure=0.97, contrast=1.10, saturation=1.06, sharpen=0.4, cool=0.0),
        scale_frac=0.78, top_strength=0.5,
    ),
    dict(
        src="v_standard.png",
        kicker="THE STANDARD",
        head=["NOTHING OUT", "OF PLACE"],
        sub="The same discipline, corner to corner.",
        crop=dict(focus_y=0.42, focus_x=0.5, zoom=1.0),
        grade=dict(exposure=0.96, contrast=1.10, saturation=1.06, sharpen=0.4, cool=0.0),
        scale_frac=1.0, top_strength=0.5,
    ),
]

HOLD = 4.0
XFADE = 0.7
