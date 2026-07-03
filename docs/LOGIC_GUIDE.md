# LOGIC_GUIDE.md

## Purpose
Tracks architectural decisions, non-obvious tradeoffs, and resolved bugs across sessions.
Update immediately when: architecture shifts, a tradeoff is made, a recurring bug is resolved.
Do not defer updates to end-of-session.

## Entries

### 2026-07-04 — repo reorg: docs/ + assets/, code stays flat
**What:** Moved `spec.md` and `LOGIC_GUIDE.md` under `docs/`, and the bundled fonts + logo under `assets/` (compositor now anchors them via `ASSETS_DIR`). Root is now just `README.md`, `CLAUDE.md`, the Python/`.mjs` modules, and config. Updated every reference (compositor path constants, CLAUDE.md/README/spec cross-links, one test comment).
**Why:** Declutter the root and separate docs/assets from source, per the repo-cleanup goal, without touching the working import graph.
**Alternatives rejected:** moving Python modules into a `src/`/package layout — every import (`from app import …`), the pytest rootdir, and the `.mjs` subprocess path resolution assume a flat root, so it would be pure high-risk churn for a small single-operator tool. Deep `docs/` nesting (`docs/architecture/`, `docs/decisions/`) — only two docs, so a flat `docs/` is clearer.
**Accepted risks:** `CLAUDE.md` must stay at root (Claude Code loads it from the project root); untracked scratch dirs (`trash/`, `citiview_project_lean_outputs/`) were left untouched.

### 2026-07-03 — uid-stable text↔image binding, derived per-image copy, previews
**What:** Slides now join uploaded files to sequence entries by a stable client `uid` (browser posts an aligned `upload_uids` list), not by basename. Uploads write to per-upload subdirs so duplicate basenames don't overwrite. `refine_copy` tiers per-image copy LLM → `derive_default_copy` → blank, and `/analyze-sequence/` always attaches it; the shared `_DEFAULT_COPY` constant was deleted. Added per-image thumbnail previews and `_slides_from_sequence` fail-loud 400s (misaligned/duplicate/unknown uid).
**Why:** Every slide reused one hardcoded fallback triple whenever per-image copy was empty ("all empty" rendered as "all identical"); duplicate basenames overwrote each other on disk; typed copy was silently dropped once Analyze ran.
**Alternatives rejected:** basename/`image_ref` join (collides on duplicate filenames); positional index (breaks on reorder); a single shared default copy (the bug itself).
**Accepted risks:** vision-unavailable batches classify all photos `ambiguous_mixed` with identical grounded context, so their derived copy can match — flagged for review; operator edits by hand.

### 2026-07-04 — corrected step order, single grounded copy path, crasher fixes
**What:** UI renumbered to a real dependency chain (Add photos → Event details → Analyze & Sequence → Review → Export) with disable-until-ready gating and the Review panel hidden until Analyze. Removed the generic `/generate-copy/` button + route so grounded copy (inside Analyze) is the only copy path. Fixed three confirmed crashers: R1 (corrupt-but-present image is skipped in the compositor, not a 500), R2 (`_slides_from_metadata` validates length/shape → 400, parity with the sequence path), R3 (`output_name` required + `build_output_paths` suffixes `outputs/<base>[-N]/` to avoid clobber). Aligned `CLAUDE.md`/`spec.md` and added a top-level `README.md`.
**Why:** The first actionable control (generic copy) sat above the dropzone yet demanded "drop files first"; two look-alike copy mechanisms confused users; and a parallel review surfaced real 500s + an output-clobber hazard.
**Alternatives rejected:** keeping/relabeling the generic copy button (still two mechanisms); hide-until-valid gating (less discoverable than disable+hint); timestamped output names (less predictable than reject-blank + numeric suffix).
**Accepted risks:** R7 (image referenced by no sequence entry silently excluded) and R9 (Success names an mp4 ffmpeg never wrote) left as documented risks; frontend JS has no automated browser test (verified via served-HTML markers + manual boot).
