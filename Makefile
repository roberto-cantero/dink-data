# Shortcuts for the common commands. Run `make check` before opening a PR.
.PHONY: setup lint typecheck test check

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
