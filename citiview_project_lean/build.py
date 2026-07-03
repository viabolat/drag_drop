#!/usr/bin/env python3
"""
CitiView AV — build runner.

Usage:
    python build.py <event>

    <event> is the name of a config in events/ (without .py), e.g.:
        python build.py texas
        python build.py vienna

Produces exactly two files in outputs/:
    CitiViewAV_<EVENT>_4x5.pdf
    CitiViewAV_<EVENT>.mp4

Slides are rendered to a temporary work dir and are NOT delivered (per brief:
only the PDF + MP4 are outputs).
"""
import os
import sys
import re
import importlib
import tempfile

# make engine importable when run from project root
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from engine import renderer as R
from engine import assemble as A


def _fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_event(name):
    # Security: only allow a simple identifier, no path traversal.
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        _fail(f"invalid event name '{name}' (use letters/digits/underscore only)")
    try:
        return importlib.import_module(f"events.{name}")
    except ModuleNotFoundError:
        _fail(f"no config found at events/{name}.py")


def resolve_input(event_dir, filename):
    # Security: reject anything that isn't a plain filename in the event dir.
    if os.path.basename(filename) != filename:
        _fail(f"slide src '{filename}' must be a bare filename (no paths)")
    path = os.path.join(event_dir, filename)
    if not os.path.isfile(path):
        _fail(f"missing input image: {path}")
    return path


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    name = sys.argv[1].strip()
    cfg = load_event(name)

    event_dir = os.path.join(R.INPUTS, name)
    if not os.path.isdir(event_dir):
        _fail(f"missing input folder: {event_dir}  (put this event's photos there)")

    os.makedirs(R.OUTPUTS, exist_ok=True)

    with tempfile.TemporaryDirectory() as work:
        slide_paths = []

        # content slides
        for i, s in enumerate(cfg.SLIDES, start=1):
            src = resolve_input(event_dir, s["src"])
            grade_kw = s.get("grade", cfg.GRADING)
            out = os.path.join(work, f"slide{i}.png")
            R.build_slide(
                src_path=src,
                crop_kw=s["crop"],
                grade_kw=grade_kw,
                kicker=s["kicker"],
                head_lines=s["head"],
                sub=s["sub"],
                scale_frac=s.get("scale_frac", 0.5),
                stamp=cfg.STAMP,
                top_strength=s.get("top_strength", 0.5),
                enable_fader_strip=getattr(cfg, "FADER", True),
                out=out,
            )
            slide_paths.append(out)

        # end card
        endcard_bg = resolve_input(event_dir, cfg.ENDCARD_BG)
        endcard_out = os.path.join(work, f"slide{len(cfg.SLIDES)+1}.png")
        R.build_endcard(endcard_bg, cfg.FOOTER, out=endcard_out)
        slide_paths.append(endcard_out)

        # deliverables
        pdf_out = os.path.join(R.OUTPUTS, f"CitiViewAV_{cfg.EVENT}_4x5.pdf")
        mp4_out = os.path.join(R.OUTPUTS, f"CitiViewAV_{cfg.EVENT}.mp4")

        A.build_pdf(slide_paths, pdf_out)
        _, total = A.build_mp4(
            slide_paths, mp4_out,
            hold=getattr(cfg, "HOLD", 4.0),
            xfade=getattr(cfg, "XFADE", 0.7),
        )

    print(f"Built {len(cfg.SLIDES)} slides + end card")
    print(f"  PDF: {pdf_out}")
    print(f"  MP4: {mp4_out}  ({total}s)")
    if total < 20:
        print(f"  NOTE: {total}s is under the brief's ~20-30s floor. "
              f"Raise HOLD (~4.9s) or add a slide to land in range.")


if __name__ == "__main__":
    main()
