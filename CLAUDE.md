# CLAUDE.md

<!-- Read at the start of every Claude Code session in this repo. Keep it short
     (under ~150 lines). Put detail in docs/ and link to it. -->

## Project

DinkData computes per-player pickleball stats from single-camera PickleCam
video. A Python pipeline turns a game video into an event log (rallies, hits,
bounces, players), and pure functions turn the event log into stats.

Stage: **P0 (foundations)**. The repo root still holds the prototype: a
TrackNetV3 fork retrained to track the ball, plus a rally-segmentation notebook.
New code goes under `pipeline/`, `stats/`, `contracts/` and `eval/` (see Layout).
A web app comes later (P3).

## Commands

Only the prototype commands exist today. Rows marked _planned_ are the target
for P0. Until they exist, say that you could not run them; don't claim you did.

| Purpose | Command |
|---|---|
| Install (prototype) | `pip install -r requirements.txt` (pins are stale, see FAILURE-LOG F3) |
| Ball tracking on a video (prototype) | `python predict.py --video_file <video.mp4> --tracknet_file ckpts/TrackNet_best.pt --inpaintnet_file ckpts/InpaintNet_best.pt --save_dir prediction` |
| Train ball tracker (prototype) | see `README.md` › Training |
| Install | _planned_ `uv sync` |
| Lint / format | _planned_ `uv run ruff check . && uv run ruff format --check .` |
| Unit tests | _planned_ `uv run pytest -q` |
| Accuracy eval on held-out court | _planned_ `uv run dink-cv eval --split heldout` |
| Run pipeline on a clip | _planned_ `uv run dink-cv run <clip.mp4> --out out/` |
| Overlay video for debugging | _planned_ `uv run dink-cv render out/events.json <clip.mp4>` |
| **Full pre-PR check** | _planned_ `make check` (lint + tests + eval smoke test) |

## Layout and ownership

| Path | What | Owner |
|---|---|---|
| `pipeline/court/` | calibration, homography, court lines | Partner A |
| `pipeline/ball/` | TrackNet ball tracking, bounces, in/out | Partner A |
| `pipeline/players/` | player detection, tracking, IDs, pose | Partner B |
| `pipeline/events/` | hits, rallies, score tracker, `events.json` | Partner B |
| `stats/` | pure `events -> stats` functions | Partner B |
| `contracts/` | JSON Schemas for the four handoff files | both |
| `eval/` | gold-set scoring harness | both |
| repo root `*.py`, `*.ipynb`, `utils/` | prototype, being ported | both |

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
- `data/`, `ckpts/` and `prediction/` are gitignored. `keypoints/` is not in the
  repo either but isn't ignored yet; don't commit it. Scripts take paths as arguments.

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
  change `contracts/` alone · disable tests or lint rules to make a check pass
- **Ask first:** new dependencies · contract or schema changes · the other
  partner's area · CI or eval config · changing a stat definition
- **Go ahead:** everything else inside the task
