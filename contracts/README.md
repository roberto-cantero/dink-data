# Contracts

The file formats passed between pipeline stages. The source of truth is the pydantic models in
`src/dinkdata/contracts/`. The JSON Schemas in this folder are generated from those models, and
CI fails if they are out of date. Don't edit them by hand. `docs/DESIGN.md` section 7 lists
every format, and ADR 0005 records the decision.

`events.schema.json` and `events.example.json` are the earlier draft. The Contracts v1 ticket
replaces them with the generated schemas.

Changing a contract needs a version bump and approval from both owners.
