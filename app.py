import os
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


def sanitize_upload_filename(filename: str) -> str:
    # reason: filename is attacker-controlled; without this, "../../etc/x" style names
    # escape UPLOAD_DIR via os.path.join (path traversal)
    safe_name = os.path.basename(filename)
    if safe_name in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    file_path = os.path.join(UPLOAD_DIR, safe_name)
    if not os.path.abspath(file_path).startswith(os.path.abspath(UPLOAD_DIR) + os.sep):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    return file_path

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
            let fileArray = [];

            dropzone.addEventListener('click', () => fileInput.click());
            dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('border-zinc-600'); });
            dropzone.addEventListener('dragleave', () => dropzone.classList.remove('border-zinc-600'));
            dropzone.addEventListener('drop', (e) => {
                e.preventDefault();
                dropzone.classList.remove('border-zinc-600');
                handleFiles(e.dataTransfer.files);
            });
            fileInput.addEventListener('change', () => handleFiles(fileInput.files));

            function handleFiles(files) {
                for (let file of files) {
                    fileArray.push(file);
                    const idx = fileArray.length - 1;
                    
                    const card = document.createElement('div');
                    card.className = "bg-zinc-950 p-4 border border-zinc-800 rounded-lg grid grid-cols-3 gap-4 items-center";
                    card.innerHTML = `
                        <div class="text-xs text-zinc-400 truncate font-mono">${file.name}</div>
                        <div class="col-span-2 space-y-2">
                            <input type="text" placeholder="Kicker (e.g. ARENA)" id="kicker_${idx}" class="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-red-500">
                            <input type="text" placeholder="Headline (3-6 words)" id="headline_${idx}" class="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-red-500">
                            <input type="text" placeholder="Ethos Sub Line" id="sub_${idx}" class="w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-red-500">
                        </div>
                    `;
                    queueContainer.appendChild(card);
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
                    document.getElementById(`kicker_${i}`).value = slide.kicker;
                    document.getElementById(`headline_${i}`).value = slide.headline;
                    document.getElementById(`sub_${i}`).value = slide.sub;
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

            async function analyzeSequence() {
                if (fileArray.length === 0) { alert("Please drop files first."); return; }
                const status = document.getElementById("analysisStatus");
                status.textContent = "Analyzing " + fileArray.length + " image(s)…";
                const formData = new FormData();
                for (let i = 0; i < fileArray.length; i++) formData.append("files", fileArray[i]);
                formData.append("event_context", document.getElementById("copyContext").value);
                formData.append("generate_copy", document.getElementById("genCopy").checked ? "true" : "false");
                try {
                    const response = await fetch('/analyze-sequence/', { method: 'POST', body: formData });
                    const result = await response.json();
                    analysis = (result.analyses || []).map(a => ({
                        image_ref: a.image_ref,
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
                    }));
                    const flagged = analysis.filter(a => a.review_required).length;
                    status.textContent = "Proposed sequence ready — " + analysis.length + " image(s), "
                        + flagged + " flagged for review.";
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
                    return `
                    <div class="bg-zinc-950 p-4 border ${border} rounded-lg space-y-3">
                        <div class="flex items-center gap-3">
                            <div class="flex flex-col">
                                <button type="button" onclick="moveItem(${i},-1)" class="text-zinc-500 hover:text-white text-xs leading-none">&#9650;</button>
                                <button type="button" onclick="moveItem(${i},1)" class="text-zinc-500 hover:text-white text-xs leading-none">&#9660;</button>
                            </div>
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
                for (let i = 0; i < fileArray.length; i++) formData.append("files", fileArray[i]);

                if (analysis) {
                    // reorder-safe path: sequence order + per-image copy, joined by image_ref on the server
                    const sequence = analysis.map((a, i) => ({
                        image_ref: a.image_ref,
                        sequence_index: i,
                        state_label: a.state_label,
                        kicker: a.kicker || "PRODUCTION",
                        headline: a.headline || "CRAFT IN EXECUTION",
                        sub: a.sub || "Unseen architecture working behind the scene."
                    }));
                    formData.append("sequence_json", JSON.stringify(sequence));
                } else {
                    // legacy positional path (unchanged): per-file cards, index-aligned
                    let metadata = [];
                    for (let i = 0; i < fileArray.length; i++) {
                        metadata.push({
                            kicker: document.getElementById(`kicker_${i}`).value || "PRODUCTION",
                            headline: document.getElementById(`headline_${i}`).value || "CRAFT IN EXECUTION",
                            sub: document.getElementById(`sub_${i}`).value || "Unseen architecture working behind the scene."
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
        for file in files:
            file_path = sanitize_upload_filename(file.filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            written_paths.append(file_path)

        analyses = analyze_and_sequence(written_paths, event_context, get_vision_analyzer())
        copies = refine_copy(analyses) if generate_copy else [None] * len(analyses)

        idx_by_path = {p: i for i, p in enumerate(written_paths)}
        out = []
        for a, copy in zip(analyses, copies):
            d = a.to_dict()
            # image_ref (uploaded basename) is the join key back to files on /generate-post/;
            # upload_index disambiguates should basenames collide.
            d["image_ref"] = os.path.basename(a.image_path)
            d["upload_index"] = idx_by_path.get(a.image_path)
            if copy is not None:
                d["copy"] = copy
            out.append(d)
    finally:
        for path in written_paths:
            if os.path.exists(path):
                os.remove(path)

    return {"analyses": out}


def _slides_from_metadata(metadata_json, files, written_paths):
    """Legacy positional path: files[idx] paired with metadata[idx] by index (unchanged)."""
    try:
        metadata = json.loads(metadata_json)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid data shape arrays.")
    slides_dataset = []
    for idx, file in enumerate(files):
        file_path = sanitize_upload_filename(file.filename)
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


def _slides_from_sequence(sequence_json, files, written_paths):
    """New reorder-safe path: build slides in operator-approved sequence order, joining each
    sequence entry to its uploaded file by image_ref (basename) — NEVER by positional index."""
    try:
        sequence = json.loads(sequence_json)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid data shape arrays.")
    path_by_ref = {}
    for file in files:
        file_path = sanitize_upload_filename(file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        written_paths.append(file_path)
        path_by_ref[os.path.basename(file_path)] = file_path

    ordered = sorted(sequence, key=lambda e: e.get("sequence_index", 0))
    n = len(ordered)
    slides_dataset = []
    for pos, entry in enumerate(ordered):
        file_path = path_by_ref.get(entry.get("image_ref"))
        if file_path is None:
            continue  # a sequence entry with no matching upload is skipped, not fatal
        slide = {
            "path": file_path,
            "kicker": entry.get("kicker") or "PRODUCTION",
            "headline": entry.get("headline") or "CRAFT IN EXECUTION",
            "sub": entry.get("sub") or "Unseen architecture working behind the scene.",
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
    files: list[UploadFile] = File(...)
):
    written_paths = []  # reason: tracked separately so a partial write still gets cleaned up
    try:
        if sequence_json is not None:
            slides_dataset = _slides_from_sequence(sequence_json, files, written_paths)
        else:
            # legacy positional contract (metadata_json required when no sequence provided)
            slides_dataset = _slides_from_metadata(metadata_json, files, written_paths)

        # Trigger independent compositing pipeline pass execution cleanly
        outputs = render_post_package(slides_dataset, output_base_name=output_name)
    finally:
        # reason: must run even if metadata indexing or compositing raises, so uploads never linger
        for path in written_paths:
            if os.path.exists(path):
                os.remove(path)

    if not outputs:
        raise HTTPException(status_code=500, detail="Render generation fault.")

    return {
        "status": "Success",
        "message": f"Assets generated inside working directory: {outputs['mp4']} and {outputs['pdf']}"
    }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)