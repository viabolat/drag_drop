# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-operator local web tool ("Campaign Studio") that turns a batch of event photos into
branded social media assets: a portrait MP4 slideshow and a matching PDF deck. There is no database, no
auth, and no persistence beyond the generated output files — see `docs/spec.md` for the full feature
spec and known open questions/bugs, and `docs/LOGIC_GUIDE.md` for the decision log.

## Commands

```bash
./run.sh                                        # one-command bootstrap + launch (venv, pip, npm, .env, doctor, :8000)
make test                                       # bootstrap test deps + run the suite (108 tests; hermetic)
make doctor                                     # report optional runtime deps (ffmpeg / node / agent SDK / token)
make css                                        # regenerate static/tailwind.css after editing classes in app.py
```

Manual equivalents (what run.sh does): `python3 -m venv .venv` (Python 3.12, see `.python-version`),
`.venv/bin/pip install -r requirements-dev.txt`, `npm install`, `cp .env.example .env`,
`.venv/bin/python app.py`, `.venv/bin/python -m pytest -v`.

`requirements.txt` (runtime) and `requirements-dev.txt` (adds test deps) are **pinned** — bump versions
deliberately and re-run the suite; never loosen back to `>=` ranges. CI (`.github/workflows/ci.yml`)
runs the suite + a syntax check of the `.mjs` bridges on every push/PR.

`ffmpeg` must be installed and on `PATH` for MP4 generation — it is invoked via `subprocess`, not pip, and
is **not** listed in `requirements.txt`. If missing (or if ffmpeg fails), `compositor._build_mp4` reports
failure, `render_post_package` returns `"mp4": None`, and the `/generate-post/` response says
"MP4 not produced" — the PDF is still delivered (R9, resolved).

Fonts (`SairaCondensed-Bold.ttf`, `Barlow-Regular.ttf`) and the brand logo (`logo_cn_white.png`) are
bundled in `assets/` (referenced via `compositor.ASSETS_DIR`) — there is no runtime network
dependency for rendering.

An optional `CLAUDE_CODE_OAUTH_TOKEN` (a Claude Code subscription token, generated via
`claude setup-token`, loaded via `.env`/`python-dotenv`) enables AI-generated slide copy through
`text_generation.py` → `generate_slide_copy.mjs` **and** per-image vision analysis through
`vision_provider.py` → `analyze_image.mjs`; without it, both degrade to a clearly `[MOCK]`-prefixed
placeholder / all-zero-confidence signal vector rather than failing. `node` must be on `PATH` for
these features — if missing, the same mock fallback applies. Both `.mjs` bridges **reject
`ANTHROPIC_API_KEY`** (exit 2) to keep usage on subscription billing, never metered API billing.

## Image lifecycle analysis & sequencing layer

Layered on top of the render pipeline (no compositor change — it already honors caller order +
per-slide `scale_frac`). Decides what each photo represents in an event's lifecycle, orders the
photos by a deterministic multi-signal engine, and assigns the **correct** grounded per-image
Event Context. Three invariants: **filenames are never a sequencing signal**; **EXIF metadata is
strictly secondary** (tie-break / conflict-flag only, `DateTimeOriginal` only, never mtime); **the
LLM never orders** (vision emits per-image signals with no order field; deterministic Python owns
sequencing).

- **`analyze_image.mjs`** — Node/ESM vision bridge; the ONLY multimodal use of the Agent SDK. Sends
  one base64 image + instruction as a streamed `SDKUserMessage` (`query({prompt: AsyncIterable})`,
  `model:'haiku'`, `maxTurns:1`, `allowedTools:[]`). Prints a signals-only JSON object (no order
  field). Same auth-gate / tolerant-parse / `[MOCK]`-fallback pattern as `generate_slide_copy.mjs`.
- **`vision_provider.py`** — the pluggable `VisionAnalyzer` seam. `ClaudeVisionAnalyzer` downscales
  in Python (Pillow, bounded 1536px JPEG — node stays image-library-free) then shells to the bridge
  with one fast-fail retry; `DictVisionAnalyzer` injects canned signals in tests; `safe_analyze`
  enforces never-raise and reports `vision_unavailable`. Tests mock this seam so node/Claude never
  runs in the suite.
- **`image_signals.py`** — objective CV (numpy Laplacian-variance / edge-density / colorfulness /
  brightness, Pillow fallback), EXIF `DateTimeOriginal`, and 64-bit aHash for near-dup detection.
- **`image_analysis.py`** — the deterministic engine: gated macro-phase classification (hard gates
  for live/teardown, template affinity along the venue→final continuum), intra-bucket ordering by
  completeness with EXIF tie-break/conflict, confidence calibration, and review routing.
- **`lifecycle_taxonomy.py`** (all tunable constants/weights/thresholds), **`analysis_schema.py`**
  (`SignalReading`, `ImageAnalysis`), **`context_generation.py`** (grounded per-image context +
  `derive_default_copy`/`refine_copy`, which tier per-image copy LLM → derived → blank; the old
  shared constant fallback was deleted).
- **`app.py`** — `POST /analyze-sequence/` (analyze + propose order, returns the schema for the
  review UI; `get_vision_analyzer()` is the test patch point). It **always** attaches per-image
  `copy` via `context_generation.refine_copy(analyses, use_llm=...)` (tiered LLM → derived → blank);
  the `generate_copy` flag gates only the optional live-LLM tier. `POST /generate-post/` gained an
  optional `sequence_json` that builds `slides_dataset` by **stable client `uid` keyed join** (each
  sequence entry carries its `uid`; the browser also posts an aligned `upload_uids` list), **not**
  basename and not positional index — this is the reorder-safe, duplicate-basename-safe path.
  `_slides_from_sequence` **fails loudly with HTTP 400** on missing/misaligned `upload_uids`, a
  duplicate uid, or a sequence entry whose uid has no uploaded file. When `sequence_json` is absent
  the legacy positional `metadata_json` path runs (now also **400-validated** for length/shape).
  The UI is a numbered 5-step flow — Add photos → Event details → Analyze & Sequence → Review
  (reorder / relabel / edit context + copy / remove / add) → Export — with per-image thumbnail
  previews, copy that migrates from the upload cards into the review panel (then the cards go
  read-only), and prerequisite gating (Analyze/Export disabled until a photo exists; the review panel
  hidden until Analyze runs). Item management is client-side hard delete + incremental add:
  `removeItem(uid)` (confirm-gated, on both upload cards and review rows) drops the photo from
  `fileArray` and `analysis` in one step; photos added after Analyze are analyzed **incrementally**
  (only the new files posted to `/analyze-sequence/`) and appended to the sequence — existing rows and
  edits are never re-derived, and cross-set ordering/near-dup detection is NOT recomputed (operator
  repositions manually). Export uploads only files whose uid is in the sequence, so
  staged-but-unanalyzed photos (failed incremental analyze → status message + retry) can't silently
  diverge from the render. There is a single copy path: the old generic `/generate-copy/` button/route
  was **removed**.

Known: opaque Claude Code subprocess failures under rapid sequential vision calls (surface as the
bridge's terse "Claude Code process exited with code 1"; root cause unconfirmed). Such images
degrade to `ambiguous_mixed` + `vision_unavailable` + review after a bounded retry (exponential
backoff with jitter, sequential — never parallel), never a crash.

## Architecture

Four-file pipeline (three Python, one Node) plus the small `theme.py` brand seam, no framework
beyond FastAPI for routing:

- **`app.py`** — FastAPI app with four routes (plus a `/static` mount for the vendored Tailwind
  snapshot — regen with `make css` after editing classes; the page loads with zero network access):
  - `GET /health` returns the preflight doctor report (`ffmpeg`/`node`/`agent_sdk`/`token` presence
    + human-readable `warnings`). Pure inspection — degradation behavior is unchanged. The UI fetches
    it on load and shows dismissible banners; `print_preflight()` prints the same at startup.
  - `GET /` returns a single self-contained HTML page (no build step; brand chrome injected from
    `theme.py` via `{{TOKEN}}` sentinel replacement — the HTML is a plain string, never an f-string)
    with inline vanilla JS for the drag-and-drop UI, laid out as a numbered 5-step flow (Add photos → Event
    details → Analyze & Sequence → Review → Export). Each uploaded file gets a stable client `uid`, a
    thumbnail preview, a confirm-gated **Remove photo** control, and three free-text fields (`kicker`,
    `headline`, `sub`) that map 1:1 to slide overlay text. The Review panel adds per-row **Remove**
    and a **+ Add more photos** button (incremental analyze of just the new files, appended to the
    sequence). Analyze is disabled until ≥1 photo exists; Export until ≥1 *active* (in-sequence)
    photo; the Review panel is hidden until Analyze runs. There is a single copy path — the old
    generic `/generate-copy/` route was removed.
  - `POST /analyze-sequence/` accepts `files`, `event_context` (free-text), and `generate_copy`
    (bool). It classifies each photo's lifecycle state, orders them deterministically, grounds a
    per-image Event Context, and **always** attaches per-image `copy` (`refine_copy`, tiered
    LLM → derived → blank; `generate_copy` gates only the LLM tier). Returns the review schema —
    `image_ref` for display plus `upload_index` to bind each row back to the browser's uid.
    `get_vision_analyzer()` is the test patch point.
  - `POST /generate-post/` accepts `output_name` (required, non-blank), `files` (multipart), and
    either `sequence_json` + an aligned `upload_uids` list (reorder-safe, joined by **uid**, 400 on
    misalignment/duplicate/unknown uid) or the legacy `metadata_json` (index-aligned; length/shape
    400-validated). It writes uploads under per-upload subdirs in `temp_uploads/` (so duplicate
    basenames don't collide), calls `compositor.render_post_package`, deletes the temp uploads, and
    returns the resulting `mp4`/`pdf` paths under `outputs/<base>/`.

- **`compositor.py`** — pure image/video rendering, no web concerns:
  - `render_post_package(slides_dataset, output_base_name)` is the single entry point. `slides_dataset`
    is a list of `{path, kicker, headline, sub}` dicts.
  - Fixed output canvas: `OUTPUT_WIDTH=1080 x OUTPUT_HEIGHT=1350` (portrait, Instagram-story-shaped).
  - Per-slide pipeline: `_grade` (an unconditional colour grade from `DEFAULT_GRADE` —
    exposure/contrast/saturation/sharpen — plus optional per-slide `grade`/`crop` overrides) →
    center-crop to target aspect ratio → resize → top + bottom gradient scrims + vignette → composite
    the bundled logo (top-left, `LOGO_HEIGHT=96`) → top-right LOCATION/TAGLINE stamp → right-edge
    FADER tick strip → draw brand text (the headline is rendered to a transparent layer and
    affine-sheared by a fixed `SHEAR=+0.16` for the italic brand look; the kicker is letter-tracked,
    not sheared) → bottom-right contact URL.
  - The last slide's image is reused (blurred + darkened) to auto-generate an outro/end card with a
    fixed tagline and contact info — there's no way to opt out of the end card per-run.
  - Slides are written as numbered JPEGs (`slide_{idx:03d}.jpg`, `slide_end.jpg`) inside an
    auto-deleted `tempfile.TemporaryDirectory(prefix="campaign_render_")`, combined into the PDF via
    `Pillow`'s multi-page save and into the MP4 via a chained `ffmpeg -filter_complex xfade` graph
    (crossfades, not hard cuts) shelled out through `subprocess`. Because the frames live in a temp
    dir, a crash mid-render leaves **no** orphaned artifacts. Final deliverables land under
    `outputs/<base>/<base>.{pdf,mp4}` (via `build_output_paths`, which claims the first free
    `outputs/<base>[-N]/` so repeat runs never clobber). A corrupt-but-present source image is
    skipped, not fatal.

- **`text_generation.py`** — optional LLM-assisted slide copy, no web/rendering concerns:
  - `generate_slide_copy(context, slide_count)` is the single entry point — a free-text event
    description in, a list of `{kicker, headline, sub}` dicts out (one per slide, index-aligned).
  - Delegates to `generate_slide_copy.mjs` via `subprocess.run(["node", ...])` (one-shot, no
    long-running Node process) and parses its JSON stdout; catches subprocess timeouts, a
    non-Node environment, and malformed/mismatched output, degrading to a `[MOCK]`-prefixed
    placeholder in every case instead of raising — callers never need to handle an error path.

- **`generate_slide_copy.mjs`** — Node/ESM script; one of two Claude Agent SDK bridges (the other is
  `analyze_image.mjs`, used for per-image vision analysis). Used only by `refine_copy`'s LLM tier:
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

- Brand values live in **`theme.py`** (a frozen `Theme` dataclass whose defaults are a *neutral,
  unbranded placeholder*, optionally overridden by the single active brand file — `ACTIVE_BRAND=<name>`
  → `brands/<name>.json`, or `BRAND_CONFIG=<path>` → that exact file, which wins if both are set;
  either may come from the shell or `.env`, which `theme.py` loads itself so import order can't
  swallow it. There is no repo-root `brand.json` fallback and no UI picker — one active theme per
  installation. `brands/*.json` is gitignored per-installation config; `brands/_example.json.template`
  is the tracked schema template. A missing/malformed file or an unknown `ACTIVE_BRAND` name logs a
  warning and falls back to defaults, never breaks a render. The default `logo_path` is `""`, which
  `compositor._logo_content()` treats as "no logo" — slides stamp `brand_short` text and the end card
  renders `brand_full` instead.) `compositor.py` rebinds the historical module-level names (`ACCENT_RED`, `TAGLINE_1`,
  `DISPLAY_FONT_PATH`, …) from `THEME`, so draw calls and external imports are unchanged; the canvas
  size, scrim geometry, and MP4 spec stay fixed constants in `compositor.py`. `text_generation.py` /
  `vision_provider.py` pass `BRAND_NAME`/`BRAND_DESCRIPTION` to the `.mjs` bridges via subprocess env
  (prompt flavor only — never auth, and never touching the `ANTHROPIC_API_KEY` rejection).
- The inline `<script>` in `app.py` is plain browser JS, not a bundled frontend — do not introduce
  `async def` (Python syntax) there; it must be `async function`.
- Intermediate render frames now live in a per-run `tempfile.TemporaryDirectory` (unique prefix), so
  they no longer collide across runs. The remaining concurrency caveat is `outputs/<base>/`: two runs
  sharing an `output_name` would target the same folder, but `build_output_paths` claims the first
  free `outputs/<base>[-N]/` to avoid clobber. Still a single-operator tool, not built for truly
  parallel compile requests.
- Never hardcode `CLAUDE_CODE_OAUTH_TOKEN` (or any credential) into source — it belongs in a local
  `.env`, gitignored, loaded via `python-dotenv` (Python side) / inherited `process.env` (Node side).
  `generate_slide_copy.mjs` explicitly rejects `ANTHROPIC_API_KEY` if set, to keep usage on
  subscription billing rather than silently falling back to metered API billing — this check must
  not be removed or weakened.
- The repo is under git with a `.gitignore` that already covers `.env`, `node_modules/`,
  `outputs/`, and `temp_uploads/`. `package-lock.json` is **tracked** (reproducible Node installs)
  and `.env.example` is the committed template for the optional token.
