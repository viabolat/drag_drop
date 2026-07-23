# Convenience targets — ./run.sh is the canonical one-command entry point.
.PHONY: setup run dev test doctor css

# Bootstrap everything and launch the app (idempotent).
run:
	./run.sh

# Bootstrap only (no launch): venv + runtime deps + node deps + .env.
setup:
	PYTHON_BIN=$${PYTHON_BIN:-python3} bash -c '\
		[ -x .venv/bin/python ] || $$PYTHON_BIN -m venv .venv; \
		.venv/bin/pip install --quiet -r requirements-dev.txt; \
		command -v npm >/dev/null && npm install --no-fund --no-audit || true; \
		[ -f .env ] || cp .env.example .env'

# Test deps + full hermetic suite.
dev: setup
test: dev
	.venv/bin/python -m pytest -v

# Report optional runtime dependencies (ffmpeg / node / agent SDK / token).
doctor:
	.venv/bin/python -c "import app; app.print_preflight()"

# Regenerate the vendored Tailwind snapshot after editing classes in app.py.
# (Dev-time only — requires network for npx; the served page itself is fully offline.)
css:
	printf '@tailwind base;\n@tailwind components;\n@tailwind utilities;\n' > /tmp/tw_input.css
	npx -y tailwindcss@3.4.17 -i /tmp/tw_input.css -o static/tailwind.css --content app.py --minify
