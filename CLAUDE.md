# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-operator local web tool ("CitiView AV — Campaign Studio") that turns a batch of event photos into
branded social media assets: a portrait MP4 slideshow and a matching PDF deck. There is no database, no
auth, and no persistence beyond the generated output files — see `spec.md` for the full feature spec and
known open questions/bugs.

## Commands

```bash
pip install -r requirements.txt   # deps: fastapi, uvicorn, Pillow, python-multipart, python-dotenv
npm install                        # deps: @anthropic-ai/claude-agent-sdk (Node, for slide-copy generation)
python app.py                      # serves the UI + API at http://127.0.0.1:8000
.venv/bin/python -m pytest -v      # run the test suite (29 tests, tests/ + pytest.ini)
```

`ffmpeg` must be installed and on `PATH` for MP4 generation — it is invoked via `subprocess`, not pip, and
is **not** listed in `requirements.txt`. If missing, `compositor.render_post_package` catches
`FileNotFoundError`, logs a notice, and still returns an `mp4` path that doesn't exist on disk.

Fonts (`SairaCondensed-Bold.ttf`, `Barlow-Regular.ttf`) and the brand logo (`logo_cn_white.png`) are
bundled directly in the repo root — there is no runtime network dependency for rendering.

An optional `CLAUDE_CODE_OAUTH_TOKEN` (a Claude Code subscription token, generated via
`claude setup-token`, loaded via `.env`/`python-dotenv`) enables AI-generated slide copy through
`text_generation.py` → `generate_slide_copy.mjs`; without it, that feature degrades to a clearly
`[MOCK]`-prefixed placeholder rather than failing. `node` must be on `PATH` for this feature —
if missing, the same mock fallback applies.

## Architecture

Four-file pipeline (three Python, one Node), no framework beyond FastAPI for routing:

- **`app.py`** — FastAPI app with three routes:
  - `GET /` returns a single self-contained HTML page (Tailwind via CDN, no build step) with inline
    vanilla JS for the drag-and-drop UI. Per uploaded file, the UI collects three free-text fields
    (`kicker`, `headline`, `sub`) that map 1:1 to slide overlay text. An "Auto-generate copy" button
    calls `/generate-copy/` and fills those fields in-place.
  - `POST /generate-copy/` accepts `context` (free-text form field) and `count` (int), calls
    `text_generation.generate_slide_copy`, and returns `{"slides": [...]}` — a list of
    `{kicker, headline, sub}` dicts, index-aligned to the upload order, meant to prefill (not replace)
    the per-photo fields before the user edits/submits.
  - `POST /generate-post/` accepts `output_name` (form field), `metadata_json` (JSON-encoded array of
    `{kicker, headline, sub}`, index-aligned with the uploaded files), and `files` (multipart list).
    It writes uploads to `temp_uploads/`, calls `compositor.render_post_package`, deletes the temp
    uploads, and returns the resulting `mp4`/`pdf` paths. Uploaded file order and `metadata_json` order
    **must stay index-aligned** — there's no filename-based matching.

- **`compositor.py`** — pure image/video rendering, no web concerns:
  - `render_post_package(slides_dataset, output_base_name)` is the single entry point. `slides_dataset`
    is a list of `{path, kicker, headline, sub}` dicts.
  - Fixed output canvas: `OUTPUT_WIDTH=1080 x OUTPUT_HEIGHT=1350` (portrait, Instagram-story-shaped).
  - Per-slide pipeline: center-crop to target aspect ratio → resize → a mild luminance-gated exposure
    pass (`ImageStat` mean < 60 → +10% brightness lift; otherwise a light `UnsharpMask`) → paste a
    bottom gradient scrim → composite the bundled logo (top-left, `LOGO_HEIGHT=90`) → draw brand text
    (kicker/headline are rendered to a transparent layer and affine-sheared by a fixed -0.16 shear
    factor before compositing, to get the italicized brand look).
  - The last slide's image is reused (blurred + darkened) to auto-generate an outro/end card with a
    fixed tagline and contact info — there's no way to opt out of the end card per-run.
  - Slides are written as numbered temp JPEGs (`__ui_slide_{idx}.jpg`, `__ui_slide_end.jpg`) in the
    project root, combined into the PDF via `Pillow`'s multi-page save, and combined into the MP4 via
    a chained `ffmpeg -filter_complex xfade` graph (crossfades, not hard cuts) shelled out through
    `subprocess`. All temp slide files are deleted at the end of the function — a crash mid-render
    will leave orphaned `__ui_slide_*.jpg` files in the project root.

- **`text_generation.py`** — optional LLM-assisted slide copy, no web/rendering concerns:
  - `generate_slide_copy(context, slide_count)` is the single entry point — a free-text event
    description in, a list of `{kicker, headline, sub}` dicts out (one per slide, index-aligned).
  - Delegates to `generate_slide_copy.mjs` via `subprocess.run(["node", ...])` (one-shot, no
    long-running Node process) and parses its JSON stdout; catches subprocess timeouts, a
    non-Node environment, and malformed/mismatched output, degrading to a `[MOCK]`-prefixed
    placeholder in every case instead of raising — callers never need to handle an error path.

- **`generate_slide_copy.mjs`** — Node/ESM script, the only place the Claude Agent SDK is used:
  - Ported from an external reference pair (`claude_token_template.md` outline +
    `quoting-engine.ts` real-world example) — same auth-gate, hermetic single-turn `query()` call,
    and tolerant JSON parsing pattern.
  - `resolveAuth()` **rejects `ANTHROPIC_API_KEY` outright** (throws, exit code 2) even if a valid
    `CLAUDE_CODE_OAUTH_TOKEN` is also set — the two must never coexist, since a stray API key would
    silently route usage onto metered billing instead of the intended Claude Code subscription
    channel. Falls back to `[MOCK]`-prefixed output when neither is set (this is a single-operator
    local tool with no deployment concept, so "no token" is never a hard failure).
  - `query()` is called hermetically: `maxTurns: 1`, `allowedTools: []`, `settingSources: []` — no
    tool use, no CLAUDE.md/settings loaded, behaves like a plain structured completion.
  - Requires `npm install` (adds `@anthropic-ai/claude-agent-sdk` per `package.json`) — this is a
    Node-only SDK; there is no Python port, hence the subprocess bridge from `text_generation.py`.

## Conventions specific to this repo

- Brand constants (`ACCENT_RED`, `PURE_WHITE`, `SILVER_TEXT`, canvas size, shear factor, scrim height,
  logo size) are hardcoded at the top of `compositor.py` — there is no config file or theming layer.
  Changing the visual brand means editing these constants and the draw calls directly.
- The inline `<script>` in `app.py` is plain browser JS, not a bundled frontend — do not introduce
  `async def` (Python syntax) there; it must be `async function`.
- Filenames for intermediate render artifacts are non-namespaced (`__ui_slide_*.jpg`), so this pipeline
  is not safe for concurrent/parallel compile requests.
- Never hardcode `CLAUDE_CODE_OAUTH_TOKEN` (or any credential) into source — it belongs in a local
  `.env`, gitignored, loaded via `python-dotenv` (Python side) / inherited `process.env` (Node side).
  `generate_slide_copy.mjs` explicitly rejects `ANTHROPIC_API_KEY` if set, to keep usage on
  subscription billing rather than silently falling back to metered API billing — this check must
  not be removed or weakened.
- No git repo exists in this directory yet, so `node_modules/`, `package-lock.json`, and any future
  `.env` are not currently gitignored anywhere — add a `.gitignore` before running `git init`.
