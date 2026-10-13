# Contracts

The pipeline is split into stages that hand work to each other through four
files. Each file's format is defined here as a JSON Schema, so either partner
can build and test their side without waiting for the other.

| File | Made by | Used by | What it holds |
|---|---|---|---|
| `court.json` | A (court) | B | Homography (image px to court ft, ground plane only), court keypoints, both kitchen lines and the net, per camera |
| `ball.parquet` | A (ball) | B | Per frame: ball x, y, visible, confidence. Per bounce: court x, y, in or out, close call |
| `players.parquet` | B (players) | A | Per frame: player id, team, box, foot position on court, wrist points |
| `events.json` (event log v1) | B (events), with A's bounces and shot types | `stats/`, later the app | Rallies, hits, bounces, shot types, winners, score |

Court coordinates follow `docs/COURT.md`, and the stats built from `events.json`
follow `docs/STATS.md`.

## Files in this folder

For each handoff file, add:

- `<name>.schema.json`: the JSON Schema (draft 2020-12). For the Parquet files,
  the schema describes one row.
- `<name>.example.json`: a small, synthetic example that must validate against it.

`tests/contracts/test_schemas.py` checks every schema against its example.

## Rules

- Changing a schema requires a version bump and approval from both partners (see `CLAUDE.md`).
- Every detected event carries `conf` (0 to 1).
- Human corrections are stored as patches on top of model output, never by overwriting it.
- Examples are synthetic: no real players, videos or locations.
