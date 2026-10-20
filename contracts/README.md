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

Each `*.example.json` is a synthetic example that validates against its schema. The pydantic
models also check rules JSON Schema can't express, such as ordering, ids and the score as
played. `highlights.check_highlights` checks a reel file against `events.json` or
`rallies.json`.

Changing a contract needs a version bump and approval from both owners.
