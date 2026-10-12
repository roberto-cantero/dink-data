# CLAUDE.md

<!-- Read at the start of every Claude Code session in this repo. Keep it short
     (under ~150 lines). Put detail in docs/ and link to it. -->

## Project

DinkData computes per-player pickleball stats from single-camera PickleCam
video. A Python pipeline turns a game video into an event log (rallies, hits,
bounces, players), and pure functions turn the event log into stats.

Stage: **P0 (foundations)**. `legacy/` holds the prototype: a TrackNetV3 fork
retrained to track the ball, plus a rally-segmentation notebook.
New code goes under `pipeline/`, `stats/`, `contracts/` and `eval/` (see Layout).
A web app comes later (P3).

## Commands

Rows marked _planned_ don't exist yet. Until they do, say that you could not
run them; don't claim you did.

| Purpose | Command |
|---|---|
| Install (CPU torch + git hooks) | `make setup` (= `uv sync --extra cpu` + `uv run pre-commit install`) |
| Install on an NVIDIA GPU machine | `uv sync --extra cu126` (add `--extra players` for ultralytics) |
| Lint / format | `make lint` (= `uv run ruff check . && uv run ruff format --check .`) |
| Type check | `make typecheck` (= `uv run pyright`) |
| Unit tests | `make test` (= `uv run pytest -q -m "not gpu and not data"`) |
| CLI | `uv run dink-cv --help` |
| Accuracy eval on held-out court | _planned_ `uv run dink-cv eval --split heldout` |
| Run pipeline on a clip | _planned_ `uv run dink-cv run <clip.mp4> --out out/` |
| Overlay video for debugging | _planned_ `uv run dink-cv render out/events.json <clip.mp4>` |
| **Full pre-PR check** | `make check` (lint + type check + tests; eval smoke test _planned_) |
| Prototype (reference only) | `legacy/` scripts; pins in `legacy/requirements.txt` are stale (FAILURE-LOG F3) |

## Layout and ownership

Partner A is Robby (`@roberto-cantero`, label `owner:Robby`). Partner B is Marti
(`@probablynotmarti`, label `owner:Marti`).

| Path | What | Owner |
|---|---|---|
| `pipeline/court/` | calibration, homography, court lines | Partner A |
| `pipeline/ball/` | TrackNet ball tracking, bounces, in/out | Partner A |
| `pipeline/players/` | player detection, tracking, IDs, pose | Partner B |
| `pipeline/events/` | hits, rallies, score tracker, `events.json` | Partner B |
| `stats/` | pure `events -> stats` functions | Partner B |
| `contracts/` | JSON Schemas for the four handoff files | both |
| `eval/` | gold-set scoring harness | both |
| `tests/` | mirrors the packages; synthetic fixtures in `tests/fixtures/` | both |
| `legacy/` | prototype, being ported (paths in FAILURE-LOG predate the move) | both |

Ask before changing code owned by the other partner. When porting prototype
code, move it into the new layout with tests; don't build on it in place.

## Court geometry

Full details: `docs/COURT.md`.

- Units are feet. Origin = far-left baseline corner as seen from the camera.
  x runs 0-20 across, y runs 0-44 toward the camera. Net at y=22, kitchen lines at y=15 and y=29.
- The homography is only valid for points on the ground: player feet and ball
  bounces. Never project an airborne ball through it.
- No hardcoded pixel thresholds. Take the net, lines and zones from the calibration.
- Time is measured in frames. Read fps from the video; never assume 30.

## Stats

Definitions: `docs/STATS.md`. A stat's code must match its definition there.
Changing a definition means updating the doc, its tests and telling the other
partner in the PR.

## Contracts

- `contracts/*.schema.json` will define `court.json`, `ball.parquet`,
  `players.parquet` and `events.json` (v1). Changing them requires a version
  bump and approval from both partners.
- Every detected event carries `conf` (0-1). Human corrections are stored as
  patches on top of model output, never by overwriting it.
- Stats are pure functions of the event log. Each one gets a unit test built from
  a hand-written event log.

## Accuracy rules

- Any change to a model, threshold or heuristic: put held-out-court eval scores
  (before and after) in the PR description.
- Never train or tune on the held-out court. Split data by match or court, never by rally.

## Data

- Never commit videos, frames, checkpoints or labels. They live in `FILL-IN: bucket or drive`.
- `data/`, `ckpts/`, `keypoints/`, `prediction/`, `out/`, videos, model weights and
  `*.parquet` (outside `tests/fixtures/`) are gitignored. Scripts take paths as arguments.

## Platform

- Must run on Windows and macOS (development) and on Linux + CUDA (cloud GPU workers).
- Use `pathlib`; no hardcoded path separators. Pick the device automatically (cuda, mps, cpu).
- No file or model loading at import time.
- Processing runs on cloud GPUs from a Docker image. Keep the image runnable
  locally on CPU for small clips.

## Known problems

`docs/FAILURE-LOG.md` lists known bugs and design mistakes in the prototype.
Check it before working in an area, and add to it when you find a new one.

## Boundaries

- **Never:** commit secrets, `.env` files, data or checkpoints · push to `main` ·
  change `contracts/` alone · disable tests or lint rules to make a check pass ·
  put footage, personal data or client details in code, commits, issues, PRs or logs
- **Ask first:** new dependencies · contract or schema changes · the other
  partner's area · CI or eval config · changing a stat definition
- **Go ahead:** everything else inside the task
