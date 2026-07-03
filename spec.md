# Spec: CitiView AV Campaign Studio — Drag & Drop Post Compiler

## Problem Statement
CitiView AV (event production/AV company) needs a local tool for staff to turn raw event photos into branded social media assets without manual design work in Photoshop/Premiere. A staff member should be able to drag in a batch of photos, type a kicker/headline/sub-line per photo, and receive a finished Instagram-ready video (MP4) and PDF deck with consistent branding (CitiView AV logo, red accent, sheared display type) applied automatically.

## Success Criteria
- User drags/drops or browses multiple images into the single-page UI (`app.py` `/` route) and can attach a kicker, headline, and sub-line to each image before compiling.
- `POST /generate-post/` accepts the images + JSON metadata, and `compositor.render_post_package` produces:
  - One branded 1080×1350 JPEG slide per uploaded photo (crop-to-fit, brand overlays, sheared kicker/headline text, bottom scrim).
  - An auto-generated outro/end card (blurred final photo + tagline + contact info).
  - A single PDF containing all slides in order (`{output_name}.pdf`).
  - A single MP4 slideshow (4s/slide, H.264, no audio) built via system `ffmpeg` (`{output_name}.mp4`).
- Temp uploads and intermediate render frames are cleaned up after each run (no orphaned files in `temp_uploads/` or project root).
- Runs locally via `uvicorn` on `127.0.0.1:8000` with no external services beyond first-run font downloads (Saira Condensed, DejaVu Sans from GitHub raw).

## Out of Scope
- Cloud hosting/deployment, multi-user auth, or job queuing (this is a single-operator local tool).
- Video formats other than MP4, or slide aspect ratios other than the fixed 1080×1350 portrait format.
- Editing/reordering slides after upload, or persisting past campaigns/history.
- Any Supabase/Groq/AI-generation integration — this is a deterministic image-compositing pipeline, not an LLM feature.

## Known Constraints
- **`ffmpeg` is a hard runtime dependency** invoked via `subprocess` but is not installable via pip and is absent from `requirements.txt` — must be present on `PATH` on the host, or MP4 generation silently fails (caught `FileNotFoundError`, prints a notice, still returns the (nonexistent) mp4 path to the client).
- Fonts are fetched from `raw.githubusercontent.com` on first render call; no offline fallback bundling the `.ttf` files locally.
- Single-process, synchronous, in-memory pipeline — not designed for concurrent compile jobs (no locking around shared temp filenames like `__ui_slide_*.jpg` / `ui_input.txt`).

## Open Questions
- `compositor.py:69` references `ImageStat` but the module is never imported, so the `'ImageStat' in globals()` guard is always `False` — the "smart level correction" (shadow recovery) branch never executes and every image silently takes the unsharp-mask path instead. Confirm whether this is intentional or a bug to fix.
- `app.py`'s inline `<script>` defines `async def executeCompilation()` (Python syntax) instead of `async function executeCompilation()` — this is invalid JavaScript and will throw a parse error in the browser, breaking the compile button entirely. Needs confirmation this hasn't been noticed/fixed yet.
- Should `ffmpeg` be a documented prerequisite (README/setup script) or should the app degrade gracefully (skip MP4, still deliver PDF) instead of returning a broken mp4 path when ffmpeg is missing?
- Is `temp_uploads/` expected to be git-ignored/ephemeral only, or should uploaded originals be retained for reruns?
