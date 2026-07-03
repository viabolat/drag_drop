# Spec: CitiView AV Campaign Studio — Drag & Drop Post Compiler

## Problem Statement
CitiView AV (event production/AV company) needs a local tool for staff to turn raw event photos into branded social media assets without manual design work in Photoshop/Premiere. A staff member should be able to drag in a batch of photos, type a kicker/headline/sub-line per photo, and receive a finished Instagram-ready video (MP4) and PDF deck with consistent branding (CitiView AV logo, red accent, sheared display type) applied automatically.

## Success Criteria
- User drags/drops or browses multiple images into the single-page UI (`app.py` `/` route), following a numbered 5-step flow (Add photos → Event details → Analyze & Sequence → Review → Export).
- **Analyze & Sequence** classifies each photo's event-lifecycle stage, orders them deterministically, grounds a per-image Event Context, and drafts per-image copy (the AI tier is optional; a deterministic per-photo draft is always produced). The user can reorder, relabel, and edit copy in a Review panel; text and preview stay bound to their image by a stable `uid` — safe across reorder and duplicate filenames.
- `POST /generate-post/` accepts the images + either a reorder-safe `sequence_json` (joined to files by `uid`) or legacy index-aligned `metadata_json`, and `compositor.render_post_package` produces:
  - One branded 1080×1350 JPEG slide per uploaded photo (crop-to-fit, brand overlays, sheared headline, scrims + vignette).
  - An auto-generated outro/end card (blurred final photo + tagline + contact info).
  - A single PDF containing all slides in order and a single MP4 slideshow (4s/slide, H.264, no audio) via system `ffmpeg`, written to `outputs/<base>/<base>.{pdf,mp4}`.
- Temp uploads and intermediate render frames are cleaned up after each run (no orphaned files in `temp_uploads/` or project root).
- Runs locally via `uvicorn` on `127.0.0.1:8000`. Fonts and logo are bundled in the repo (no downloads). The only optional external calls are the Claude Agent SDK bridges (grounded copy + vision) when `CLAUDE_CODE_OAUTH_TOKEN` is set; without it they degrade to `[MOCK]`/neutral signals.

## Out of Scope
- Cloud hosting/deployment, multi-user auth, or job queuing (this is a single-operator local tool).
- Video formats other than MP4, or slide aspect ratios other than the fixed 1080×1350 portrait format.
- Persisting past campaigns/history, or multi-user collaboration.
- Cloud/metered LLM billing: the optional AI copy + vision run only on a Claude Code subscription token; the `.mjs` bridges reject `ANTHROPIC_API_KEY`. (Reordering and grounded AI copy are now in scope — see Success Criteria.)

## Known Constraints
- **`ffmpeg` is a hard runtime dependency** invoked via `subprocess` but is not installable via pip and is absent from `requirements.txt` — must be present on `PATH` on the host, or MP4 generation silently fails (caught `FileNotFoundError`, prints a notice, still returns the (nonexistent) mp4 path to the client).
- Rendering is fully offline: `SairaCondensed-Bold.ttf` + `Barlow-Regular.ttf` and the logo are bundled in `assets/`; `_font` falls back to the Pillow default if a face fails to load.
- Single-process, synchronous pipeline — not designed for concurrent compile jobs. Intermediate frames live in per-run temp dirs (no shared filenames); the only shared surface is `outputs/<base>/`, which `build_output_paths` suffixes (`<base>-2`, …) to avoid clobber.

## Resolved / Open Questions
- **RESOLVED** — the old `ImageStat` / `'ImageStat' in globals()` "shadow recovery" guard is gone; `compositor.py` now grades unconditionally via `DEFAULT_GRADE` + optional per-slide overrides.
- **RESOLVED** — `executeCompilation` is a valid `async function`; the compile button works.
- **RESOLVED** — `temp_uploads/` is gitignored and ephemeral; every run deletes its uploads (per-upload subdirs pruned by `_remove_upload`).
- **PARTIALLY OPEN (R9)** — `ffmpeg` is now a documented prerequisite AND the app degrades (skips MP4, still delivers PDF). Still open: when ffmpeg is missing the response still names an `mp4` path that was never written.
- **OPEN (R7)** — an uploaded image referenced by no `sequence_json` entry is silently excluded from the render (no warning surfaced to the operator).
