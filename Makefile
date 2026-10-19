# Shortcuts for the common commands. Run `make check` before opening a PR.
.PHONY: setup lint typecheck test check design-pdf

setup:  ## install dependencies (CPU torch) and the git hooks
	uv sync --extra cpu
	uv run pre-commit install

lint:  ## ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

typecheck:  ## pyright (basic mode)
	uv run pyright

test:  ## unit tests, skipping GPU and real-data tests
	uv run pytest -q -m "not gpu and not data"

check: lint typecheck test  ## everything CI runs, before a PR

design-pdf:  ## rebuild docs/DinkData-Design.pdf from docs/DESIGN.md (needs Chrome or Chromium)
	uv run --no-project --with markdown-it-py --with mdit-py-plugins --with pymupdf python scripts/render_design.py
