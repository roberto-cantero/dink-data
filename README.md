# DinkData

DinkData turns a PickleCam recording of a doubles pickleball game into per-player stats and
highlight reels. A Python pipeline finds the court, the ball and the four players, builds a
game log of rallies, hits, bounces and rally winners, and turns that log into stats, a
one-page report and a short reel for each player. It doesn't report the score (ADR 0019).

PickleCam records about 4,500 games a day at about 140 facilities in the Philippines. DinkData
runs on its own for now. Sending stats and reels with PickleCam's video emails comes later.

## Start here

| Read | For |
|---|---|
| [`docs/DESIGN.md`](docs/DESIGN.md), or the [PDF](docs/DinkData-Design.pdf) | What we build, how and why: requirements, architecture, every pipeline stage, costs and the roadmap |
| [`GLOSSARY.md`](GLOSSARY.md) | The words we use for the game, the footage and our data |
| [`docs/adr/`](docs/adr) | Decisions and the reasons behind them |
| [`CLAUDE.md`](CLAUDE.md) | Rules for working in the repo, for people and Claude Code |
| [`docs/STATS.md`](docs/STATS.md), [`COURT.md`](docs/COURT.md), [`DATA.md`](docs/DATA.md), [`LABELLING.md`](docs/LABELLING.md), [`EVAL.md`](docs/EVAL.md), [`OPERATIONS.md`](docs/OPERATIONS.md) | Detail for each area |

## Setup

You need [uv](https://docs.astral.sh/uv/) and `make`. uv installs the right Python itself.

```bash
git clone https://github.com/roberto-cantero/dink-data.git
cd dink-data
make setup
make check
uv run dink --help
```

`make setup` installs the dependencies with CPU PyTorch and the git hooks. `make check` runs
lint, type checks and tests. GPU work runs on cloud GPUs, described in
[`docs/OPERATIONS.md`](docs/OPERATIONS.md). To reach the R2 bucket from your Mac, run
`scripts/r2-setup.sh` ([`docs/DATA.md`](docs/DATA.md), "Setting up R2").

## How we work

We build with [Matt Pocock's skills](https://github.com/mattpocock/skills) for Claude Code.
Install them once with `claude plugin install mattpocock-skills@claude-plugins-official`.

1. `/grill-with-docs` settles decisions before any code, and records terms in `GLOSSARY.md` and
   decisions in `docs/adr/`.
2. `/to-spec` writes the spec as a GitHub issue, and `/to-tickets` splits it into small tickets
   on the [DinkData board](https://github.com/users/roberto-cantero/projects/1).
3. A fresh Claude Code session takes one ticket with `/implement`, on a branch named `a/...`
   for Robby or `b/...` for Marti, and works test-first.
4. `/code-review` checks the work against the spec and our standards, and `/pr` opens the pull
   request. The other owner reviews it. Changes to a model, threshold or rule include the
   `dink eval` table from before and after.
5. Each PR is squash-merged into `main`. Nobody pushes to `main` directly.

## License

AGPL-3.0. See [`LICENSE`](LICENSE).
