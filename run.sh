#!/usr/bin/env bash
# One-command bootstrap + launch for Campaign Studio.
# Idempotent and non-privileged: it never sudo-installs anything. Missing system deps
# (ffmpeg, node) are reported by the doctor with install hints — the app still runs and
# degrades gracefully without them.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -x .venv/bin/python ]; then
    echo "[setup] creating virtualenv (.venv)…"
    "$PYTHON_BIN" -m venv .venv
fi

echo "[setup] syncing pinned Python deps…"
.venv/bin/pip install --quiet -r requirements.txt

if command -v node >/dev/null 2>&1; then
    if [ ! -d node_modules/@anthropic-ai/claude-agent-sdk ]; then
        if command -v npm >/dev/null 2>&1; then
            echo "[setup] installing Node deps (agent SDK for optional AI copy/vision)…"
            npm install --no-fund --no-audit
        else
            echo "[setup] npm not found — skipping Node deps (AI features stay in MOCK mode)."
        fi
    fi
else
    echo "[setup] node not found — AI copy/vision will run in MOCK mode."
    echo "        hint: install Node >=18, e.g. https://nodejs.org or your distro packages."
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "[setup] ffmpeg not found — MP4 export disabled (PDF still works)."
    echo "        hint: sudo apt install ffmpeg"
fi

if [ ! -f .env ] && [ -f .env.example ]; then
    echo "[setup] creating .env from .env.example (token optional — see README)."
    cp .env.example .env
fi

echo
.venv/bin/python -c "import app; app.print_preflight()"
echo
echo "[run] serving at http://127.0.0.1:8000 (Ctrl+C to stop)"
exec .venv/bin/python app.py
