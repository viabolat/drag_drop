import os
import json
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse
import uvicorn
import shutil
from compositor import render_post_package
from text_generation import generate_slide_copy

app = FastAPI()
UPLOAD_DIR = "./temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


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

            async function executeCompilation() {  // reason: was invalid Python-style syntax, broke compile button in browser
                if(fileArray.length === 0) { alert("Please drop files first."); return; }
                
                const formData = new FormData();
                formData.append("output_name", document.getElementsByName("output_name")[0].value);
                
                let metadata = [];
                for(let i=0; i < fileArray.length; i++) {
                    formData.append("files", fileArray[i]);
                    metadata.push({
                        kicker: document.getElementById(`kicker_${i}`).value || "PRODUCTION",
                        headline: document.getElementById(`headline_${i}`).value || "CRAFT IN EXECUTION",
                        sub: document.getElementById(`sub_${i}`).value || "Unseen architecture working behind the scene."
                    });
                }
                formData.append("metadata_json", JSON.stringify(metadata));

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

@app.post("/generate-post/")
async def generate_post(
    output_name: str = Form(...),
    metadata_json: str = Form(...),
    files: list[UploadFile] = File(...)
):
    try:
        metadata = json.loads(metadata_json)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid data shape arrays.")

    slides_dataset = []
    written_paths = []  # reason: tracked separately so a partial write (e.g. bad metadata index) still gets cleaned up
    try:
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

        # Trigger independent compositing pipeline pass execution cleanly
        outputs = render_post_package(slides_dataset, output_base_name=output_name)
    finally:
        # reason: must run even if metadata indexing or compositing raises, so uploads never linger in temp_uploads/
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