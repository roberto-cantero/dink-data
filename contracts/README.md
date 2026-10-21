# Contracts

The file formats passed between pipeline stages. The source of truth is the pydantic models in
`src/dinkdata/contracts/`. The JSON Schemas in this folder are generated from those models with
`uv run dink contracts export`, and a test fails if they are out of date. Don't edit them by
hand. `docs/DESIGN.md` section 7 lists every format, and ADR 0005 records the decision.

| File | Model | Owner |
|---|---|---|
| `events.schema.json` | `game_log.EventLog`: games, rallies and serves from `games.py`, events from `events.py` | Both: Marti the games and serves, Robby the events |
| `rallies.schema.json` | `rallies.RallyLabels`, rally-level gold | Marti |
| `highlights.schema.json` | `highlights.Highlights`, one reel per game per player | Marti |
| `players.schema.json` | `players.PlayerRow`, rows of `players.parquet`. The parquet contract is `players.PLAYERS_SCHEMA` | Marti |
| `catalog.schema.json` | `catalog.CatalogRow`, rows of `catalog.parquet`. The parquet contract is `catalog.CATALOG` | Robby |
| `frames.schema.json` | `frames.FrameRow`, rows of `{video_id}.frames.parquet`. The parquet contract is `frames.FRAMES` | Robby |
| `camera.schema.json` | `camera.CameraCalibration`, one calibration of one camera | Robby |
| `ball.schema.json` | `ball.BallRow`, rows of `ball.parquet`. The parquet contract is `ball.BALL` | Robby |
| `candidates.schema.json` | `candidates.CandidateRow`, rows of `candidates.parquet`. The parquet contract is `candidates.CANDIDATES` | Robby |
| `ball_labels.schema.json` | `ball.BallLabelRow`, rows of `ball_labels.parquet`. The parquet contract is `ball.BALL_LABELS` | Robby |
| `stats.schema.json` | `stats.Stats`, one entry per game, subject and stat | Robby |
| `patch.schema.json` | `patch.Patch`, corrections to one run. `patch.apply_patch` gives the patched `events.json` | Robby |

Each `*.example.json` is a synthetic example that validates against its schema. The pydantic
models also check rules JSON Schema can't express, such as ordering, ids and the score as
played. `highlights.check_highlights` checks a reel file against `events.json` or
`rallies.json`. `frames.check_log_frames`, `camera.check_log_camera` and `stats.check_stats`
check `events.json` against its frame table, its calibration and its stats. The Parquet
contracts share `tables.TableContract`, which reads, writes and validates a whole table.

Changing a contract needs a version bump and approval from both owners.
