# CLAUDE.md

<!-- Read at the start of every Claude Code session in this repo. Keep it under 150 lines.
     Put detail in docs/ and link to it. -->

## Project

DinkData turns a PickleCam recording of a doubles pickleball game into per-player stats and
highlight reels. The pipeline finds the court, ball and players, builds a game log of rallies,
hits, bounces and the score, and pure functions turn the game log into stats and reels.

The first goal is a prototype accurate enough to impress PickleCam's CEO, built on about 150
games downloaded by hand. Automatic intake, delivery to players and production cost come after
it (ADR 0018). Don't build them before then.

`docs/DESIGN.md` is the source of truth for what we build and why. Read the section for your
area before starting. If another doc disagrees with it, follow `DESIGN.md` and flag the
conflict in your PR. `GLOSSARY.md` fixes the words we use. `docs/adr/` records decisions.

Stage: setup phase. M0 starts once its tickets are on the board (`docs/DESIGN.md` section 14).

## Commands

Rows marked _planned_ don't exist yet. If you couldn't run something, say so.

| Purpose | Command |
|---|---|
| Install with CPU PyTorch and git hooks | `make setup` |
| Install on a GPU machine (always pair `cv` with `cpu` or `cu126`) | `uv sync --extra cv --extra cu126` |
| Lint and format check | `make lint` |
| Type check | `make typecheck` |
| Unit tests | `make test` |
| Full pre-PR check: lint, types, tests and pre-commit hooks | `make check` |
| CLI | `uv run dink --help` |
| Regenerate `contracts/*.schema.json` after changing a contract model | `uv run dink contracts export` |
| Opaque id for a hand-downloaded game | `uv run --env-file .env dink id video` |
| Label rallies in the browser (video in `data/videos/<video_id>.mp4`) | `uv run dink studio --rallies <video_id> --labeller <handle>` |
| Rebuild the design PDF after editing `docs/DESIGN.md` | `make design-pdf` |
| Run the pipeline on a recording | _planned_ `uv run dink run <video_id>` |
| Accuracy eval | _planned_ `uv run dink eval --run <run_id> --split test` |

## Layout and ownership

Robby is `@roberto-cantero` (`owner:Robby`). Marti is `@probablynotmarti` (`owner:Marti`).

| Path | What | Owner |
|---|---|---|
| `src/dinkdata/data/`, `video/` | catalog, sampling, fetch, frame-accurate reading | Robby |
| `src/dinkdata/court/` | calibration, floor mapping, visibility | Robby |
| `src/dinkdata/ball/` | background images, ball tracker | Robby |
| `src/dinkdata/events/` | event spotter, rally grammar | Robby |
| `src/dinkdata/stats/`, `report/` | stats and the report | Robby |
| `src/dinkdata/players/` | detection, tracking, ids, serve states, game mode, rallies | Marti |
| `src/dinkdata/score/` | score decoder | Marti |
| `src/dinkdata/highlights/` | reel selection and rendering | Marti |
| `src/dinkdata/contracts/`, `eval/`, `studio/` | file formats, evaluation, labelling tool | both |
| `tests/` | mirrors `src/dinkdata/`, synthetic fixtures only | both |

Ask before changing the other owner's area.

## Rules

- **Time.** Use frame timestamps. Never compute time as `frame / 30`, because PickleCam videos
  drop frames. A pre-commit check catches it.
- **Court.** Positions are in feet (`docs/COURT.md`). The court mapping is only valid for
  points on the floor, such as feet and bounces, never a ball in the air. No hardcoded pixel
  thresholds.
- **Contracts.** File formats are pydantic models in `src/dinkdata/contracts/`, with generated
  JSON Schemas in `contracts/`. Validate files at run time. Every detection has `conf`.
  Changing a contract needs a version bump and both owners' approval.
- **Corrections.** Human corrections are patches on top of model output, never overwrites.
- **Stats.** Definitions live in `docs/STATS.md`. Code must match them, and every rule gets a
  unit test from a hand-written game log.
- **Accuracy.** Any change to a model, threshold or rule puts the `dink eval` table, before
  and after, in the PR (`docs/EVAL.md`). Test sets are whole held-out facilities. Never train
  or tune on test data. Gold labels never train.
- **Data and privacy.** Data lives in the Cloudflare R2 bucket `dinkdata` (`docs/DATA.md`).
  Never commit videos, frames, checkpoints, labels or `.env`. No emails, facility names,
  session ids or Bunny ids in code, commits, issues, PRs or logs.
- **Cost.** GPU work runs on cloud GPUs in one Docker image. Use the cheapest GPU that gives
  the same result, but never cut quality to save money (`docs/OPERATIONS.md`).
- **Platform.** Code runs on macOS for development and Linux for GPU work, not Windows. Use
  `pathlib`. Pick the device automatically (cuda, mps, cpu). Load no files or models at
  import time.
- **No legacy code.** Don't reuse code from the `legacy-prototype` tag or TrackNetV3. Write
  from the papers and `docs/DESIGN.md` (ADR 0001).

## Writing

Docs, comments, issues and PRs follow the unslop rules:
- Write plain, active sentences, one idea each.
- No AI filler words (crucial, delve, leverage, robust, seamless).
- No em dashes, arrows in prose, or inline-header lists.
- Say what something does or give the number, not how it feels.

## Known problems

`docs/KNOWN-ISSUES.md` lists known bugs. Check it before working in an area, and add to it when
you find a new one. ADR 0001 lists the prototype's lessons.

## Agent skills

We build with Matt Pocock's skills (`mattpocock-skills` plugin): `/grill-with-docs`, `/to-spec`,
`/to-tickets`, `/implement` (one ticket per fresh session, test-first), `/code-review`, `/pr`
and `/retro`. `docs/DESIGN.md` section 12.2 describes the flow.

### Issue tracker

GitHub Issues on `roberto-cantero/dink-data`, via `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Boundaries

- **Never:** commit secrets, `.env` files, data or checkpoints · push to `main` ·
  change `contracts/` alone · disable tests or lint rules to make a check pass ·
  put footage, personal data or client details in code, commits, issues, PRs or logs
- **Ask first:** new dependencies · contract or schema changes · the other owner's area ·
  CI or eval config · changing a stat definition · spending beyond the monthly budget
- **Go ahead:** everything else inside the ticket
