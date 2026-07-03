# CitiView AV — Campaign Studio

Turn a batch of raw event photos into branded social assets — a portrait **MP4 slideshow** and a
matching **PDF deck** — without opening Photoshop or Premiere. It runs entirely on your own machine.

> This README has two halves: **[For operators](#for-operators)** (how to use it) and
> **[For developers](#for-developers)** (how it's built and how to work on it safely).

---

## What it is

A single-operator, local web tool. You drag in event photos, the tool figures out the story they
tell (empty room → setup → live show → teardown), orders them, drafts on-brand caption text for
each, and exports a finished 1080×1350 portrait video + PDF with the CitiView AV logo, red accent,
and sheared display type applied automatically.

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

1. **Add Photos** — drag & drop (or browse) your event photos. A thumbnail preview appears for each.
2. **Event Details** — give the output a file name (required) and, optionally, a one-line **Event
   Context** (e.g. *"Corporate gala, downtown Austin, LED wall + stage lighting"*). That context is
   used in the next step to keep the wording tied to the real event.
3. **Analyze & Sequence** — click to have the tool read each photo, order them by event stage, and
   write a grounded description of each. Tick **"also draft slide copy from each photo"** to have it
   draft kicker/headline/sub text too. *(Enabled once you've added at least one photo.)*
4. **Review, Edit & Reorder** — appears after Analyze. Reorder with the arrows, fix a mislabeled
   stage, and edit the context or copy for any photo. **Your edits always win.**
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

```bash
pip install -r requirements.txt   # fastapi, uvicorn, Pillow, numpy, python-multipart, python-dotenv
npm install                       # @anthropic-ai/claude-agent-sdk (Node bridges: copy + vision)
python app.py                     # serves UI + API at http://127.0.0.1:8000
.venv/bin/python -m pytest -v     # 92 tests
```

- **`ffmpeg`** must be on `PATH` for MP4 output (invoked via `subprocess`; not a pip dep). If it's
  missing, the PDF is still produced and a notice is logged.
- **Optional AI** — set `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) in a local `.env`. It
  enables AI-drafted copy and per-image vision analysis. Without it, both degrade to a clearly
  `[MOCK]`/neutral fallback rather than failing. `node` must be on `PATH`. The `.mjs` bridges
  **reject `ANTHROPIC_API_KEY`** to keep usage on subscription billing, never metered API billing.
- Fonts (`SairaCondensed-Bold.ttf`, `Barlow-Regular.ttf`) and the logo (`logo_cn_white.png`) are
  bundled in the repo — rendering has no network dependency.

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
and previews survive reorder and duplicate filenames. Brand constants (colors, canvas size, logo
size, shear) are hardcoded at the top of `compositor.py`. See **`CLAUDE.md`** for a deeper module
tour and **`LOGIC_GUIDE.md`** for the decision log.

### Limitations / failure modes / known edge cases

- **ffmpeg missing** → PDF is delivered but no MP4 (the response currently still names the mp4 path
  that wasn't written — known risk *R9*).
- **Vision unavailable** (no token / node / a transient bridge failure) → every photo is labeled
  `ambiguous_mixed` and flagged for review, and their grounded copy can look alike. Fix by editing
  copy per row in Step 4 (it binds correctly to each image).
- **Single operator** — no auth, no persistence/history. Not built for truly concurrent compiles;
  repeat runs with the same output name are auto-suffixed (`<base>-2`, …) to avoid clobber.
- **Silent exclusion (R7)** — an uploaded image left out of the reviewed sequence is dropped from the
  render without a warning.
