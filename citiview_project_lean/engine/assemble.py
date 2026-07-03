#!/usr/bin/env python3
"""
Assembly — turn rendered slide PNGs into the two deliverables (PDF + MP4).

MP4 spec (locked): 1080x1350, 30fps, silent, H.264/yuv420p, CRF 17, +faststart.
Static holds + crossfades (no Ken Burns). Timing comes from the event config.
"""
import os
import shutil
import subprocess
from PIL import Image


def build_pdf(slide_paths, out_path):
    slides = [Image.open(p).convert("RGB") for p in slide_paths]
    slides[0].save(out_path, save_all=True, append_images=slides[1:], resolution=300.0)
    return out_path


def build_mp4(slide_paths, out_path, hold=4.0, xfade=0.7, fps=30, crf=17):
    """Chain slides with crossfades via ffmpeg xfade.
    Total duration = n*hold - (n-1)*xfade."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH. Install ffmpeg to build the MP4.")
    n = len(slide_paths)

    inputs = []
    for p in slide_paths:
        inputs += ["-loop", "1", "-t", str(hold), "-i", p]

    # format/fps normalisation per input
    filt = []
    for i in range(n):
        filt.append(f"[{i}:v]format=yuv420p,fps={fps},setsar=1[v{i}]")
    # chained xfades
    prev = "v0"
    offset = 0.0
    for i in range(1, n):
        offset += hold - xfade
        out_lbl = f"x{i}" if i < n - 1 else "vout"
        filt.append(
            f"[{prev}][v{i}]xfade=transition=fade:duration={xfade}:offset={round(offset,3)}[{out_lbl}]"
        )
        prev = out_lbl
    filter_complex = ";".join(filt)

    cmd = ["ffmpeg", "-y", "-loglevel", "error"] + inputs + [
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-c:v", "libx264", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-r", str(fps),
        out_path,
    ]
    subprocess.run(cmd, check=True)
    total = round(n * hold - (n - 1) * xfade, 2)
    return out_path, total
