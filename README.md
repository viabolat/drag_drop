# Campaign Studio

Turn a batch of raw event photos into branded social assets — a portrait **MP4 slideshow** and a
matching **PDF deck** — without opening Photoshop or Premiere. It runs entirely on your own machine.

> This README has two halves: **[For operators](#for-operators)** (how to use it) and
> **[For developers](#for-developers)** (how it's built and how to work on it safely).

---

## What it is

A single-operator, local web tool. You drag in event photos, the tool figures out the story they
tell (empty room → setup → live show → teardown), orders them, drafts on-brand caption text for
each, and exports a finished 1080×1350 portrait video + PDF with your logo, accent color, and
sheared display type applied automatically — whichever brand file is active, or a neutral
placeholder brand out of the box (see [Branding](#branding-white-label)).

## Why it was made

The production team was rebuilding the same social recap by hand for every event. This automates the
repetitive design work while keeping the operator in full control of wording and order. It's
**deterministic and offline by default**; an optional AI step can draft copy, billed only to a Claude
Code subscription (never a metered API key).

## Who it's for

- **Operators / producers** — staff who have a folder of event photos and need a polished recap fast.
- **Developers** — anyone maintaining or extending the render pipeline and analysis layer.

---

## For operators

### The workflow (5 steps, top to bottom)

The page walks you down a numbered flow. Controls stay disabled until their prerequisite is met, so
you can't get out of order.

1. **Add Photos** — drag & drop (or browse) your event photos. A thumbnail preview appears for each,
   with a **Remove photo** link if you dropped the wrong one.
2. **Event Details** — give the output a file name (required) and, optionally, a one-line **Event
   Context** (e.g. *"Corporate gala, downtown Austin, LED wall + stage lighting"*). That context is
   used in the next step to keep the wording tied to the real event.
3. **Analyze & Sequence** — click to have the tool read each photo, order them by event stage, and
   write a grounded description of each. Tick **"also draft slide copy from each photo"** to have it
   draft kicker/headline/sub text too. *(Enabled once you've added at least one photo.)*
4. **Review, Edit & Reorder** — appears after Analyze. Reorder with the arrows, fix a mislabeled
   stage, and edit the context or copy for any photo. **Your edits always win.** You can also manage
   the working set here: **Remove** drops a photo from the sequence and the export (confirmed first;
   one-way for the session — your original file on disk is untouched), and **+ Add more photos**
   analyzes just the new files and appends them to the end of the sequence, leaving your existing
   order and edits alone — use the arrows to slot them in.
5. **Compile & Export** — renders the MP4 + PDF into `outputs/<your-name>/`.

You can skip Analyze and just type copy on each photo card, then Export — but Analyze gives you
ordering and grounded copy for free.

### What "Analyze" does

It looks at each photo, works out which stage of the event it shows (empty venue, load-in, setup,
final-ready, live, teardown), puts the photos in that order, and writes a short **Event Context** — a
plain description of what that specific photo shows. Nothing about filenames is used for ordering; the
photos are judged on their actual content.

### What "auto-generate grounded copy" means

"Grounded" means the slide text is written **from each photo's own analysis**, so the words match the
picture instead of being generic. With the box ticked and a subscription token configured, AI drafts
richer copy; without it, the tool still fills in a sensible per-photo draft automatically. Either way,
you can edit every line in Step 4 — the tool never overrides what you type.

### Key features

- Drag-and-drop upload with a live thumbnail per photo.
- Automatic event-lifecycle detection + deterministic ordering (you can always reorder).
- Grounded, per-photo caption drafts (AI-assisted or deterministic).
- Text and preview stay glued to the right photo through any reorder, and duplicate filenames are
  handled correctly.
- One-click export to a branded 1080×1350 MP4 (crossfades, 4s/slide) + matching PDF, with an
  auto-generated end card.

---

## For developers

### Local setup / run

One command — prerequisites are only **Python 3.12** (see `.python-version`); **Node ≥ 18** and
**ffmpeg** are optional (features degrade gracefully without them, and the startup doctor tells
you what's missing and how to fix it):

```bash
./run.sh          # creates .venv, installs pinned deps, npm install, .env, doctor, serves :8000
```

Equivalent manual steps and extras live in the `Makefile`: `make setup` (bootstrap only, incl.
test deps), `make test` (full suite), `make doctor` (dependency report), `make css` (regenerate
the vendored Tailwind snapshot after editing classes in `app.py`).

- **`ffmpeg`** must be on `PATH` for MP4 output (invoked via `subprocess`; not a pip dep). If it's
  missing, the PDF is still produced, the response says so, and the UI shows a banner at load.
- **Optional AI** — set `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) in a local `.env`. It
  enables AI-drafted copy and per-image vision analysis. Without it, both degrade to a clearly
  `[MOCK]`/neutral fallback rather than failing. `node` must be on `PATH`. The `.mjs` bridges
  **reject `ANTHROPIC_API_KEY`** to keep usage on subscription billing, never metered API billing.
- Fonts (`SairaCondensed-Bold.ttf`, `Barlow-Regular.ttf`) and the logo (`logo_cn_white.png`) are
  bundled in `assets/`, and Tailwind is a committed snapshot (`static/tailwind.css`) — the running
  tool has **zero network dependency**, for rendering and for the page itself.
- **`GET /health`** reports the same doctor checks as JSON (`ffmpeg`/`node`/`agent_sdk`/`token`).

### Branding (white-label)

`theme.py` defines the brand. Its **built-in defaults are a neutral, unbranded placeholder** — a
fresh clone renders something sane with zero configuration (no client logo: slides fall back to the
`brand_short` text mark, the end card to `brand_full`).

Real brands live as JSON files in **`brands/`**, one per client, each overriding any subset of theme
fields — no code edits. Exactly one is active per installation, selected by env var (shell or `.env`):

| Env var | Meaning |
|---|---|
| `ACTIVE_BRAND=citiview` | loads `brands/citiview.json` (plain name — no paths, no `../`) |
| `BRAND_CONFIG=/path/to/brand.json` | loads that exact file, absolute or repo-relative. **Wins if both are set.** |
| *(neither set)* | the neutral built-in defaults |

To brand a new install: `cp brands/_example.json.template brands/acme.json`, edit it, and set
`ACTIVE_BRAND=acme` in `.env`. Colors are `[r, g, b]`; relative `*_path` values resolve against the
repo root (not against `brands/`), so `"logo_path": "assets/logo.png"` points at the shared
top-level `assets/`. Unknown keys are logged and ignored; a malformed file, a missing file, or an
unknown `ACTIVE_BRAND` name logs a warning and falls back to the defaults — a bad theme can never
break a render.

`brands/*.json` is **gitignored** (per-installation config, like `.env`); only
`brands/_example.json.template` is tracked. `brand_name`/`brand_description` only flavor the AI
prompts — auth and billing are untouched by theming. There is deliberately no per-run/UI theme
picker: one active theme keeps the render path deterministic.

An example brand file (`brands/citiview.json`), showing every commonly overridden field:

```json
{
    "accent_rgb": [225, 29, 42],
    "display_font_path": "assets/SairaCondensed-Bold.ttf",
    "body_font_path": "assets/Barlow-Regular.ttf",
    "logo_path": "assets/logo_cn_white.png",
    "tagline_1": "FULL EVENT PRODUCTION · LIGHTING · STAGING",
    "tagline_2": "SOUND · VIDEO · STREAMING",
    "contact_url": "CitiViewAV.com",
    "contact_phone": "212-632-5196",
    "brand_short": "CITIVIEW AV",
    "brand_full": "CITIVIEW AUDIO VISUAL",
    "default_output_base": "citiview_social_post",
    "ui_title": "CitiView AV — Post Production Engine",
    "ui_heading": "CAMPAIGN STUDIO",
    "ui_subtitle": "Automated Multi-Format Brand Material Compiler",
    "ui_default_output_name": "citiview_post",
    "brand_name": "CitiView AV",
    "brand_description": "an event audio-visual production company (full event production, lighting, staging, sound, video, streaming)"
}
```

### Folder map

```
.
├── README.md                     # this file — the entry point
├── CLAUDE.md                     # deeper module tour (also read by Claude Code)
├── run.sh                        # one-command bootstrap + launch  (start here)
├── Makefile                      # setup / test / doctor / css targets
├── app.py                        # FastAPI app + inline 5-step UI + /health doctor
├── theme.py                      # active brand (neutral defaults + brands/<name>.json)
├── compositor.py                 # render pipeline → outputs/<base>/<base>.{pdf,mp4}
├── image_analysis.py             # deterministic sequencing engine
├── image_signals.py              # objective CV signals + EXIF + perceptual hash
├── lifecycle_taxonomy.py         # tunable constants/weights/thresholds
├── analysis_schema.py            # SignalReading / ImageAnalysis dataclasses
├── vision_provider.py            # pluggable vision seam  ─┐ Node bridges
├── analyze_image.mjs             # Claude vision bridge    │  (subprocess,
├── context_generation.py         # grounded context + copy │   resolved from
├── text_generation.py            # copy subprocess boundary │   this dir — keep
├── generate_slide_copy.mjs       # Claude copy bridge      ─┘   alongside .py)
├── assets/                       # bundled fonts + logo
├── brands/                       # per-install brand JSON (gitignored; template is tracked)
├── static/                       # vendored Tailwind snapshot (regen: make css)
├── docs/                         # spec.md, LOGIC_GUIDE.md
├── tests/                        # pytest suite (conftest imports the root modules)
├── outputs/                      # generated deliverables (gitignored)
└── temp_uploads/                 # ephemeral upload staging (gitignored)
```

Code lives flat at the repo root on purpose: `app.py`, `tests/`, and the `.mjs` subprocess bridges
all resolve each other by bare module name / sibling path, so a `src/` package would be pure churn.

### Architecture overview

FastAPI for routing; everything else is plain Python + one Node bridge per LLM feature. No frontend
build step — the UI is inline HTML + vanilla JS served by `GET /`.

| Area | Files | Responsibility |
|---|---|---|
| Web / routes | `app.py` | `GET /` (the 5-step UI), `POST /analyze-sequence/`, `POST /generate-post/` |
| Rendering | `compositor.py` | Pure image/video compositing → `outputs/<base>/<base>.{pdf,mp4}` |
| Analysis + sequencing | `image_analysis.py`, `image_signals.py`, `lifecycle_taxonomy.py`, `analysis_schema.py`, `vision_provider.py`, `analyze_image.mjs` | Per-image signals → classify stage → deterministic order |
| Copy | `context_generation.py`, `text_generation.py`, `generate_slide_copy.mjs` | Grounded Event Context + tiered per-image copy (LLM → derived → blank) |

Key invariants: **filenames are never a sequencing signal**; **EXIF is only a tie-break**; **the LLM
never chooses order** (vision emits per-image signals; deterministic Python owns sequencing).
Files/sequence entries are joined by a stable client **`uid`** (never basename or row index), so text
and previews survive reorder and duplicate filenames. Brand values (colors, fonts, logo, taglines,
contact, shear) come from `theme.py` — neutral placeholder defaults, overridden by the active brand
file (`brands/<name>.json` via `ACTIVE_BRAND`, or any path via `BRAND_CONFIG`; see **Branding**
above); the canvas size (1080×1350) and MP4 spec stay fixed in `compositor.py`.
See **`CLAUDE.md`** for a deeper module tour, **`docs/spec.md`** for the feature spec, and
**`docs/LOGIC_GUIDE.md`** for the decision log.

### Clean-machine smoke checklist

Run this after cloning on a fresh machine (or after dependency changes) to verify deployability:

1. `./run.sh` — bootstraps everything, prints the doctor report, serves `http://127.0.0.1:8000`.
2. Check the doctor output (and the page banner) matches the machine: ffmpeg/node/token present?
3. `make test` — **108 passed** (hermetic: needs no token, no ffmpeg; seams are mocked).
4. Upload 2 photos → Analyze (expect `[MOCK]`/derived copy without a token) → Compile & Export.
5. Confirm `outputs/<name>/<name>.pdf` **and** `.mp4` exist (mp4 requires ffmpeg on PATH; without it
   the response says "MP4 not produced" and only the PDF exists).

### Limitations / failure modes / known edge cases

- **ffmpeg missing or failing** → PDF is still delivered; the response says "MP4 not produced" and
  returns no mp4 path (*R9 — resolved*: the API never names a file that wasn't written).
- **Vision unavailable** (no token / node / a transient bridge failure) → every photo is labeled
  `ambiguous_mixed` and flagged for review, and their grounded copy can look alike. Fix by editing
  copy per row in Step 4 (it binds correctly to each image).
- **Single operator** — no auth, no persistence/history. Not built for truly concurrent compiles;
  repeat runs with the same output name are auto-suffixed (`<base>-2`, …) to avoid clobber.
- **Sequence exclusion (R7 — resolved in the UI)** — the browser only uploads files whose `uid` is in
  the reviewed sequence, so the upload set and render set can't silently diverge. The server-side rule
  is unchanged: a direct API call whose upload is absent from `sequence_json` still skips that file.
