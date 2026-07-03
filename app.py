import os
import re
import json
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse
import uvicorn
import shutil
from compositor import render_post_package
from text_generation import generate_slide_copy
from image_analysis import analyze_and_sequence, compute_scale_frac
from context_generation import refine_copy
from vision_provider import ClaudeVisionAnalyzer

app = FastAPI()
UPLOAD_DIR = "./temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_vision_analyzer():
    """Factory for the vision analyzer. Isolated so tests patch app.get_vision_analyzer to a
    DictVisionAnalyzer — the real Claude/node path is never invoked in the suite."""
    return ClaudeVisionAnalyzer()


_SAFE_PREFIX_RE = re.compile(r"[^A-Za-z0-9_-]")


def sanitize_upload_filename(filename: str, prefix: str = "") -> str:
    # reason: filename is attacker-controlled; without this, "../../etc/x" style names
    # escape UPLOAD_DIR via os.path.join (path traversal)
    safe_name = os.path.basename(filename)
    if safe_name in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    # reason: two uploads sharing a basename (e.g. two "photo.jpg") would overwrite each other on
    # disk and collapse into a single image. Giving each upload its own subdir guarantees a unique
    # path while keeping the basename PRISTINE, so it can still serve as the clean display name.
    # prefix is caller/attacker-derived (upload index or client uid) so it is stripped to a safe
    # charset first — the abspath guard below remains the backstop against path traversal.
    base_dir = UPLOAD_DIR
    if prefix:
        safe_prefix = _SAFE_PREFIX_RE.sub("", str(prefix))
        if safe_prefix:
            base_dir = os.path.join(UPLOAD_DIR, safe_prefix)
            os.makedirs(base_dir, exist_ok=True)
    file_path = os.path.join(base_dir, safe_name)
    if not os.path.abspath(file_path).startswith(os.path.abspath(UPLOAD_DIR) + os.sep):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    return file_path


def _remove_upload(path: str) -> None:
    """Delete a temp upload and prune its now-empty per-upload subdir (dup-basename scheme),
    leaving UPLOAD_DIR clean. Never raises."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    parent = os.path.dirname(os.path.abspath(path))
    upload_root = os.path.abspath(UPLOAD_DIR)
    if parent != upload_root and parent.startswith(upload_root + os.sep):
        try:
            os.rmdir(parent)  # only succeeds when empty — safe to attempt unconditionally
        except OSError:
            pass

@app.get("/", response_class=HTMLResponse)
async def serve_interface():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>CitiView AV — Post Production Engine</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-zinc-950 text-zinc-100 min-h-screen p-8 font-sans">
        <div class="max-w-4xl mx-auto space-y-8">
            <header class="border-b border-zinc-800 pb-4">
                <h1 class="text-2xl font-bold tracking-tight">CITIVIEW AV — CAMPAIGN STUDIO</h1>
                <p class="text-zinc-400 text-sm mt-1">Automated Multi-Format Brand Material Compiler</p>
            </header>

            <form id="uploadForm" enctype="multipart/form-data" class="space-y-6">
                <div class="bg-zinc-900 border border-zinc-800 p-6 rounded-lg space-y-4">
                    <h2 class="text-sm font-semibold tracking-wider text-red-500 uppercase">1. Project Parameters</h2>
                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <label class="block text-xs text-zinc-400 mb-1">Output File Base Name</label>
                            <input type="text" name="output_name" value="" class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm focus:outline-none focus:border-red-500">
                        </div>
                    </div>
                    <div>
                        <label class="block text-xs text-zinc-400 mb-1">Event Context (for AI-generated slide copy, optional)</label>
                        <div class="flex gap-2">
                            <input type="text" id="copyContext" placeholder="e.g. Corporate gala, downtown Austin, LED wall + stage lighting" class="flex-1 bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm focus:outline-none focus:border-red-500">
                            <button type="button" onclick="autoGenerateCopy()" class="bg-zinc-800 hover:bg-zinc-700 text-xs font-medium text-white px-4 rounded-lg transition tracking-wide whitespace-nowrap">
                                AUTO-GENERATE COPY
                            </button>
                        </div>
                    </div>
                </div>

                <div class="bg-zinc-900 border border-zinc-800 p-6 rounded-lg space-y-4">
                    <h2 class="text-sm font-semibold tracking-wider text-red-500 uppercase">2. Media Cluster Drops</h2>
                    <div id="dropzone" class="border-2 border-dashed border-zinc-800 hover:border-zinc-700 transition rounded-lg p-8 text-center cursor-pointer">
                        <p class="text-sm text-zinc-400">Drag & drop source photos here or click to open browser window</p>
                        <input type="file" id="fileInput" name="files" multiple class="hidden" accept="image/*">
                    </div>
                    <div id="filePreviewQueue" class="space-y-3"></div>
                </div>

                <div class="bg-zinc-900 border border-zinc-800 p-6 rounded-lg space-y-4">
                    <div class="flex items-center justify-between">
                        <h2 class="text-sm font-semibold tracking-wider text-red-500 uppercase">3. Lifecycle Analysis &amp; Sequencing</h2>
                        <label class="text-xs text-zinc-400 flex items-center gap-2"><input type="checkbox" id="genCopy" class="accent-red-600"> auto-generate grounded copy</label>
                    </div>
                    <p class="text-xs text-zinc-500">Detects each photo's event-lifecycle state, orders them, and grounds the Event Context per image. Review, reorder, and relabel below before exporting.</p>
                    <button type="button" onclick="analyzeSequence()" class="w-full bg-zinc-800 hover:bg-zinc-700 font-medium text-white py-2 rounded-lg transition tracking-wide text-xs">
                        ANALYZE &amp; SEQUENCE
                    </button>
                    <div id="analysisStatus" class="text-xs text-zinc-500"></div>
                    <div id="analysisReview" class="space-y-3"></div>
                </div>

                <button type="button" onclick="executeCompilation()" class="w-full bg-red-600 hover:bg-red-700 font-medium text-white py-3 rounded-lg transition tracking-wide text-sm">
                    COMPILE RUN EXPORT
                </button>
            </form>
        </div>

        <script>
            const dropzone = document.getElementById('dropzone');
            const fileInput = document.getElementById('fileInput');
            const queueContainer = document.getElementById('filePreviewQueue');
            let fileArray = [];   // [{ file, uid, url }] — uid is the stable per-image identity
            let uidCounter = 0;   // monotonic; never reused, survives reorder, unique per drop

            dropzone.addEventListener('click', () => fileInput.click());
            dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('border-zinc-600'); });
            dropzone.addEventListener('dragleave', () => dropzone.classList.remove('border-zinc-600'));
            dropzone.addEventListener('drop', (e) => {
                e.preventDefault();
                dropzone.classList.remove('border-zinc-600');
                handleFiles(e.dataTransfer.files);
            });
            fileInput.addEventListener('change', () => handleFiles(fileInput.files));

            // Preview object URLs live for the page's lifetime (there is no per-file remove UI);
            // release them when the page is torn down so they can't leak across a reload.
            function clearObjectUrls() {
                fileArray.forEach(f => { try { URL.revokeObjectURL(f.url); } catch (e) {} });
            }
            window.addEventListener('beforeunload', clearObjectUrls);

            function handleFiles(files) {
                for (let file of files) {
                    const uid = "u" + (uidCounter++);
                    const url = URL.createObjectURL(file);   // revoked on page unload (clearObjectUrls)
                    fileArray.push({ file, uid, url });

                    const card = document.createElement('div');
                    card.id = "card_" + uid;
                    card.className = "bg-zinc-950 p-4 border border-zinc-800 rounded-lg grid grid-cols-3 gap-4 items-center";
                    card.innerHTML = `
                        <div class="space-y-2">
                            <img src="${url}" alt="" class="w-full h-24 object-cover rounded border border-zinc-800">
                            <div class="text-xs text-zinc-400 truncate font-mono">${esc(file.name)}</div>
                        </div>
                        <div class="col-span-2 space-y-2">
                            <input type="text" placeholder="Kicker (e.g. ARENA)" id="kicker_${uid}" class="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-red-500">
                            <input type="text" placeholder="Headline (3-6 words)" id="headline_${uid}" class="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-red-500">
                            <input type="text" placeholder="Ethos Sub Line" id="sub_${uid}" class="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-red-500">
                        </div>
                    `;
                    queueContainer.appendChild(card);
                    // if a sequence was already analyzed, new cards are locked too (Review owns copy)
                    if (analysis) setUploadCopyReadonly(true);
                }
            }

            async function autoGenerateCopy() {
                if (fileArray.length === 0) { alert("Please drop files first."); return; }

                const formData = new FormData();
                formData.append("context", document.getElementById("copyContext").value);
                formData.append("count", fileArray.length);

                const response = await fetch('/generate-copy/', { method: 'POST', body: formData });
                const result = await response.json();
                result.slides.forEach((slide, i) => {
                    if (!fileArray[i]) return;
                    const uid = fileArray[i].uid;
                    document.getElementById(`kicker_${uid}`).value = slide.kicker;
                    document.getElementById(`headline_${uid}`).value = slide.headline;
                    document.getElementById(`sub_${uid}`).value = slide.sub;
                });
            }

            // Mirrors lifecycle_taxonomy.STATE_LABELS + ambiguous_mixed (frontend copy of the
            // relabel vocabulary — kept in sync with the backend taxonomy).
            const STATE_LABELS = ["venue_only","pre_setup","early_setup","mid_setup","late_setup",
                                  "final_ready","live_event","post_event_teardown","ambiguous_mixed"];
            let analysis = null;  // set once ANALYZE & SEQUENCE has run

            function esc(s) {
                return String(s == null ? "" : s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
                    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
            }
            function confColor(c) { return c >= 0.7 ? "text-green-400" : (c >= 0.45 ? "text-yellow-400" : "text-red-400"); }

            function setUploadCopyReadonly(readonly) {
                // After Analyze, the Review panel is the single copy surface — lock the upload-card
                // fields so the two can't diverge (no silent drops). Editable again on a fresh page.
                fileArray.forEach(f => {
                    ["kicker_","headline_","sub_"].forEach(pre => {
                        const el = document.getElementById(pre + f.uid);
                        if (el) {
                            el.readOnly = readonly;
                            el.classList.toggle("opacity-40", readonly);
                            el.classList.toggle("cursor-not-allowed", readonly);
                            el.title = readonly ? "Copy is now edited in the Review panel below." : "";
                        }
                    });
                });
            }

            async function analyzeSequence() {
                if (fileArray.length === 0) { alert("Please drop files first."); return; }
                const status = document.getElementById("analysisStatus");
                status.textContent = "Analyzing " + fileArray.length + " image(s)…";
                const formData = new FormData();
                for (let i = 0; i < fileArray.length; i++) formData.append("files", fileArray[i].file);
                formData.append("event_context", document.getElementById("copyContext").value);
                formData.append("generate_copy", document.getElementById("genCopy").checked ? "true" : "false");
                try {
                    const response = await fetch('/analyze-sequence/', { method: 'POST', body: formData });
                    const result = await response.json();
                    analysis = (result.analyses || []).map(a => {
                        // Bind each row to its stable client uid (via upload_index) so copy AND
                        // preview follow the image through any reorder — never basename/row index.
                        const src = fileArray[a.upload_index];
                        return {
                            image_ref: a.image_ref,
                            upload_index: a.upload_index,
                            uid: src ? src.uid : null,
                            state_label: a.state_label,
                            state_confidence: a.state_confidence,
                            sequence_confidence: a.sequence_confidence,
                            review_required: a.review_required,
                            ambiguity_flags: a.ambiguity_flags || [],
                            ordering_rationale: a.ordering_rationale || "",
                            phase_summary: a.phase_summary || "",
                            event_context: a.event_context || "",
                            kicker: (a.copy && a.copy.kicker) || "",
                            headline: (a.copy && a.copy.headline) || "",
                            sub: (a.copy && a.copy.sub) || ""
                        };
                    });
                    // Single source of truth: carry any copy the operator already entered in the
                    // upload cards (typed, or filled by AUTO-GENERATE COPY) into the matching review
                    // item by uid, then lock the upload cards so Review is the only copy surface.
                    let migrated = 0;
                    analysis.forEach(a => {
                        if (!a.uid) return;
                        let moved = false;
                        [["kicker","kicker_"],["headline","headline_"],["sub","sub_"]].forEach(([field, pre]) => {
                            const el = document.getElementById(pre + a.uid);
                            if (el && el.value.trim()) { a[field] = el.value; moved = true; }
                        });
                        if (moved) migrated++;
                    });
                    setUploadCopyReadonly(true);
                    const flagged = analysis.filter(a => a.review_required).length;
                    status.textContent = "Proposed sequence ready — " + analysis.length + " image(s), "
                        + flagged + " flagged for review."
                        + (migrated ? "  Existing copy for " + migrated + " image(s) carried into Review below." : "");
                    renderReview();
                } catch (e) {
                    status.textContent = "Analysis failed: " + e;
                }
            }

            function renderReview() {
                const box = document.getElementById("analysisReview");
                if (!analysis) { box.innerHTML = ""; return; }
                box.innerHTML = analysis.map((a, i) => {
                    const border = a.review_required ? "border-red-600" : "border-zinc-800";
                    const flags = a.ambiguity_flags.map(f =>
                        `<span class="text-[10px] bg-zinc-800 text-zinc-300 px-1.5 py-0.5 rounded">${esc(f)}</span>`).join(" ");
                    const opts = STATE_LABELS.map(l =>
                        `<option value="${l}" ${l === a.state_label ? "selected" : ""}>${l}</option>`).join("");
                    // preview follows the image by uid, so reorder never desyncs thumb from row
                    const src = fileArray.find(f => f.uid === a.uid);
                    const thumb = src ? src.url : "";
                    return `
                    <div class="bg-zinc-950 p-4 border ${border} rounded-lg space-y-3">
                        <div class="flex items-center gap-3">
                            <div class="flex flex-col">
                                <button type="button" onclick="moveItem(${i},-1)" class="text-zinc-500 hover:text-white text-xs leading-none">&#9650;</button>
                                <button type="button" onclick="moveItem(${i},1)" class="text-zinc-500 hover:text-white text-xs leading-none">&#9660;</button>
                            </div>
                            <img src="${thumb}" alt="" class="w-14 h-14 object-cover rounded border border-zinc-800 shrink-0">
                            <span class="text-xs font-mono bg-red-600/20 text-red-400 px-2 py-1 rounded">#${i + 1}</span>
                            <span class="text-xs text-zinc-300 font-mono truncate flex-1">${esc(a.image_ref)}</span>
                            <select onchange="updateField(${i},'state_label',this.value)" class="bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-white">${opts}</select>
                        </div>
                        <div class="flex items-center gap-4 text-[11px]">
                            <span class="text-zinc-500">state <span class="${confColor(a.state_confidence)} font-mono">${a.state_confidence.toFixed(2)}</span></span>
                            <span class="text-zinc-500">seq <span class="${confColor(a.sequence_confidence)} font-mono">${a.sequence_confidence.toFixed(2)}</span></span>
                            <span class="text-zinc-500">${esc(a.phase_summary)}</span>
                            <span class="flex-1 text-right space-x-1">${flags}</span>
                        </div>
                        <p class="text-[11px] text-zinc-500 italic">${esc(a.ordering_rationale)}</p>
                        <textarea oninput="updateField(${i},'event_context',this.value)" rows="2" class="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-200 focus:outline-none focus:border-red-500" placeholder="Event Context for this image">${esc(a.event_context)}</textarea>
                        <div class="grid grid-cols-3 gap-2">
                            <input type="text" value="${esc(a.kicker)}" oninput="updateField(${i},'kicker',this.value)" placeholder="Kicker" class="bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-red-500">
                            <input type="text" value="${esc(a.headline)}" oninput="updateField(${i},'headline',this.value)" placeholder="Headline" class="bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-red-500">
                            <input type="text" value="${esc(a.sub)}" oninput="updateField(${i},'sub',this.value)" placeholder="Sub line" class="bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-red-500">
                        </div>
                    </div>`;
                }).join("");
            }

            function moveItem(i, dir) {
                const j = i + dir;
                if (j < 0 || j >= analysis.length) return;
                [analysis[i], analysis[j]] = [analysis[j], analysis[i]];
                renderReview();  // re-render rebinds indices; the array order IS the sequence
            }

            function updateField(i, field, value) { analysis[i][field] = value; }

            async function executeCompilation() {  // reason: was invalid Python-style syntax, broke compile button in browser
                if (fileArray.length === 0) { alert("Please drop files first."); return; }

                const formData = new FormData();
                formData.append("output_name", document.getElementsByName("output_name")[0].value);
                // Files AND their uids go in the SAME fileArray order, so the server can zip them
                // into a uid->path map and join by uid — never basename, never row index.
                const uids = [];
                for (let i = 0; i < fileArray.length; i++) {
                    formData.append("files", fileArray[i].file);
                    uids.push(fileArray[i].uid);
                }
                formData.append("upload_uids", JSON.stringify(uids));

                if (analysis) {
                    // reorder-safe path: sequence order + per-image copy, joined by uid on the server.
                    // Copy is already populated per image (LLM/derived); blank stays blank on purpose.
                    const sequence = analysis.map((a, i) => ({
                        uid: a.uid,
                        image_ref: a.image_ref,
                        sequence_index: i,
                        state_label: a.state_label,
                        kicker: a.kicker || "",
                        headline: a.headline || "",
                        sub: a.sub || ""
                    }));
                    formData.append("sequence_json", JSON.stringify(sequence));
                } else {
                    // legacy positional path: per-file cards, index-aligned. Blank stays blank.
                    let metadata = [];
                    for (let i = 0; i < fileArray.length; i++) {
                        const uid = fileArray[i].uid;
                        metadata.push({
                            kicker: document.getElementById(`kicker_${uid}`).value,
                            headline: document.getElementById(`headline_${uid}`).value,
                            sub: document.getElementById(`sub_${uid}`).value
                        });
                    }
                    formData.append("metadata_json", JSON.stringify(metadata));
                }

                const response = await fetch('/generate-post/', { method: 'POST', body: formData });
                const result = await response.json();
                alert(result.message);
            }
        </script>
    </body>
    </html>
    """

@app.post("/generate-copy/")
async def generate_copy(
    context: str = Form(""),
    count: int = Form(...)
):
    if count < 1:
        raise HTTPException(status_code=400, detail="count must be at least 1.")
    slides = generate_slide_copy(context, count)
    return {"slides": slides}

@app.post("/analyze-sequence/")
async def analyze_sequence(
    event_context: str = Form(""),
    generate_copy: bool = Form(False),
    files: list[UploadFile] = File(...)
):
    """Analyze each uploaded image's lifecycle state, order them by the deterministic engine,
    and return the proposed sequence + grounded per-image event_context for human review. Does
    NOT render. Uploaded files are written to temp, analyzed, then deleted (same pattern as
    /generate-post/). Optionally pre-fills per-image copy grounded in each image's own state."""
    written_paths = []
    try:
        # per-upload subdir prefix => two "photo.jpg" uploads stay distinct on disk
        for idx, file in enumerate(files):
            file_path = sanitize_upload_filename(file.filename, prefix=str(idx))
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            written_paths.append(file_path)

        analyses = analyze_and_sequence(written_paths, event_context, get_vision_analyzer())
        # Always attach per-image copy so the review UI is pre-populated per image and never
        # collapses to a shared constant. use_llm gates only the optional live-LLM tier; the
        # deterministic per-image derived tier is always on (see context_generation.refine_copy).
        copies = refine_copy(analyses, use_llm=generate_copy)

        idx_by_path = {p: i for i, p in enumerate(written_paths)}
        out = []
        for a, copy in zip(analyses, copies):
            d = a.to_dict()
            # image_ref is the CLEAN display basename (per-upload subdir keeps it pristine; may
            # still collide across duplicate uploads). The STABLE join key back to files on
            # /generate-post/ is the client uid, carried via upload_index below — never image_ref.
            d["image_ref"] = os.path.basename(a.image_path)
            d["upload_index"] = idx_by_path.get(a.image_path)
            d["copy"] = copy
            out.append(d)
    finally:
        for path in written_paths:
            _remove_upload(path)

    return {"analyses": out}


def _slides_from_metadata(metadata_json, files, written_paths):
    """Legacy positional path: files[idx] paired with metadata[idx] by index (unchanged)."""
    try:
        metadata = json.loads(metadata_json)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid data shape arrays.")
    slides_dataset = []
    for idx, file in enumerate(files):
        file_path = sanitize_upload_filename(file.filename, prefix=str(idx))
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        written_paths.append(file_path)
        slides_dataset.append({
            "path": file_path,
            "kicker": metadata[idx]["kicker"],
            "headline": metadata[idx]["headline"],
            "sub": metadata[idx]["sub"]
        })
    return slides_dataset


def _slides_from_sequence(sequence_json, files, written_paths, upload_uids_json):
    """Reorder-safe path: build slides in operator-approved sequence order, joining each sequence
    entry to its uploaded file by the STABLE client uid — never by basename or positional index.
    Fails loudly if the uid<->file alignment is broken, rather than silently dropping slides or
    mis-binding copy/images to the wrong file."""
    try:
        sequence = json.loads(sequence_json)
        upload_uids = json.loads(upload_uids_json) if upload_uids_json else None
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid data shape arrays.")

    # Files and uids are sent in the SAME order; validate that alignment loudly before trusting it.
    if not isinstance(upload_uids, list):
        raise HTTPException(status_code=400,
                            detail="sequence_json requires an aligned upload_uids list.")
    if len(upload_uids) != len(files):
        raise HTTPException(status_code=400,
                            detail=f"upload_uids ({len(upload_uids)}) does not align with files "
                                   f"({len(files)}).")

    path_by_uid = {}
    for uid, file in zip(upload_uids, files):
        # prefix the on-disk name with the uid so two same-basename uploads stay distinct
        file_path = sanitize_upload_filename(file.filename, prefix=str(uid))
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        written_paths.append(file_path)
        if uid in path_by_uid:
            raise HTTPException(status_code=400, detail=f"Duplicate upload uid: {uid!r}.")
        path_by_uid[uid] = file_path

    ordered = sorted(sequence, key=lambda e: e.get("sequence_index", 0))
    n = len(ordered)
    slides_dataset = []
    for pos, entry in enumerate(ordered):
        uid = entry.get("uid")
        file_path = path_by_uid.get(uid)
        if file_path is None:
            # Every sequence entry must resolve to an uploaded file by uid; a miss means the
            # text<->image binding is broken, so fail loudly rather than drop or mis-render.
            raise HTTPException(status_code=400,
                                detail=f"Sequence entry uid {uid!r} has no matching uploaded file.")
        slide = {
            "path": file_path,
            # per-image copy already resolved upstream (LLM -> derived -> blank); blank stays blank
            "kicker": entry.get("kicker") or "",
            "headline": entry.get("headline") or "",
            "sub": entry.get("sub") or "",
        }
        frac = entry.get("scale_frac")
        slide["scale_frac"] = frac if frac is not None else compute_scale_frac(
            pos, n, entry.get("state_label", ""))
        if entry.get("location"):
            slide["location"] = entry["location"]
        if entry.get("tagline"):
            slide["tagline"] = entry["tagline"]
        slides_dataset.append(slide)
    return slides_dataset


@app.post("/generate-post/")
async def generate_post(
    output_name: str = Form(...),
    metadata_json: str = Form(None),
    sequence_json: str = Form(None),
    upload_uids: str = Form(None),
    files: list[UploadFile] = File(...)
):
    written_paths = []  # reason: tracked separately so a partial write still gets cleaned up
    try:
        if sequence_json is not None:
            slides_dataset = _slides_from_sequence(sequence_json, files, written_paths, upload_uids)
        else:
            # legacy positional contract (metadata_json required when no sequence provided)
            slides_dataset = _slides_from_metadata(metadata_json, files, written_paths)

        # Trigger independent compositing pipeline pass execution cleanly
        outputs = render_post_package(slides_dataset, output_base_name=output_name)
    finally:
        # reason: must run even if metadata indexing or compositing raises, so uploads never linger
        for path in written_paths:
            _remove_upload(path)

    if not outputs:
        raise HTTPException(status_code=500, detail="Render generation fault.")

    return {
        "status": "Success",
        "message": f"Assets generated inside working directory: {outputs['mp4']} and {outputs['pdf']}"
    }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)