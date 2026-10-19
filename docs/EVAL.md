# Evaluation

How we measure accuracy and cost. Code in `src/dinkdata/eval/` follows this file.
`docs/DESIGN.md` section 10 has the reasoning, and ADR 0013 records the decision.

## The command

`dink eval --run <run_id> --split dev` or `--split test` compares a pipeline run with the gold
labels. It prints a markdown table for the PR, broken down by camera setup, and appends the
results to `eval/{run_id}.csv` in R2. A small synthetic version runs in CI.

## Metrics

| Stage | Metric |
|---|---|
| Calibration | Reprojection error in pixels on held-back clicks |
| Ball | Precision, recall and F1 within 10 px at 1080p, also at 5 and 20 px, and the median error |
| Players | Partner identity at the serve, for the near and far team separately. Hitter identities that match gold. Foot error in feet on foot clicks |
| Serve states | Server, side and team accuracy |
| Rallies | Start and end within 0.5 seconds, and missed or extra rallies |
| Hits, bounces, net | Precision, recall and F1 within 2 frames, about 67 ms |
| Attribution | Hitter accuracy among matched hits |
| Bounces | Position error in feet, in/out accuracy and close-call rate |
| Score | Exact final score per game, per-rally score accuracy and rule deviations found, reported separately for games with and without deviations |
| Stats | For each stat, the share of player-games off by at most 1 and the mean error, next to the same numbers for the median-count baseline |
| Highlights | The share of clips containing the whole rally, and the share with the marker on the right player |
| Coverage | The share of stats shipped, overall and per camera setup |
| Cost | GPU-seconds per video for each stage, and the estimated cost per video |

## Gates

| Gate | Requirement | Milestone |
|---|---|---|
| Partner identity | Measured for near and far teams, with a target agreed before M2 starts | M0 spike |
| Score ships | Exact in at least 90% of test games | M2 |
| Rally reels ship | At least 95% of clips contain the whole rally | M2 |
| Ball v1 | Recall and precision of at least 90% at 10 px on test clicks | M2 to M3 |
| Ball stats ship | Each stat off by at most 1 in at least 90% of test player-games, better than the baseline, and at or above the coverage floor for each setup | M3 |
| Events | F1 no more than 0.03 below human agreement, provisionally | M3 |
| Beta | A week of reviewed games in which reviewers change fewer than 1 stat in 10 | M4 |
| Cost | Measured compute plus bandwidth under $0.01 a video on the chosen provider | M4 |

## Rules

- Nobody trains or tunes on test data. Training uses silver labels only, and gold never trains.
- Test sets come from whole held-out facilities, covering every camera setup.
- Every change to a model, threshold or rule includes the eval table from before and after,
  with 95% confidence intervals.
- A change counts as better if the total improves and no camera setup gets worse by more than
  its interval. Results for a setup with only about 2 test games are a warning, not a verdict.
- The baseline for a count stat predicts each player's median count from the training games.
