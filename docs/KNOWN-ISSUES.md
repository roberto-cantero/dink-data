# Known issues

Bugs and design mistakes found in DinkData's code. Check this file before working in an area,
and add an entry when you find a new one. When an issue is fixed, set its status to Fixed and
link the PR. Don't delete entries.

The prototype's problems are summarised in ADR 0001.

| ID | Area | Problem | Severity | Status |
|---|---|---|---|---|
| K1 | CI | The gitleaks pre-commit hook scans only staged changes, so in CI it checks nothing | Medium | Open |
| K2 | Video | On macOS, OpenCV and PyAV each bundle FFmpeg, and importing both prints duplicate-class warnings | Low | Open |
| K3 | Data | Two people running `dink ingest` at the same time can lose catalog and id-map rows | Medium | Open |

## K1 · Gitleaks doesn't scan in CI

- Where: `.pre-commit-config.yaml` and `.github/workflows/ci.yml`
- What: the gitleaks hook checks staged changes. CI runs pre-commit with `--all-files`, where
  nothing is staged, so secrets in a PR would only be caught on the author's machine.
- Fix: add a CI step that runs `gitleaks git` over the PR's commits.

## K2 · OpenCV and PyAV both bundle FFmpeg on macOS

- Where: the `cv` extra in `pyproject.toml`, and any process that imports `cv2` and `av`
- What: each wheel ships its own `libavdevice`. On macOS, importing both prints `objc` warnings
  that the classes `AVFFrameReceiver` and `AVFAudioReceiver` are implemented twice, and that
  this may cause crashes. Those classes capture from cameras through AVFoundation, which we
  don't use. Reading files works, and the reader's tests pass with both imported. Linux is not
  affected.
- Fix: none yet. If a crash shows up, keep OpenCV out of video reading (the reader uses PyAV)
  and import `cv2` only in processes that need it.

## K3 · Parallel ingests lose catalog rows

- Where: `src/dinkdata/data/ingest.py`, in `ingest`
- What: ingest reads `catalog/catalog.parquet` and `catalog/id_map.parquet` when it starts and
  overwrites both when it ends, a few minutes later. If another ingest writes them in between,
  its new rows are lost. The video and its frames stay in R2, but the game has no catalog row,
  and its id-map row may be gone too. Worse, `choose_split` takes a game's split from its
  facility's catalog rows. If the lost row was the facility's only one, the next ingest from
  that facility looks like a new facility and accepts any `--split`. A test facility's games
  could then land in dev or train.
- Fix: until it is fixed, only one person runs ingest at a time. Running ingest again on a game
  that lost its row adds the row back. Re-ingest a lost game before ingesting anything else from
  its facility. The fix is to read and merge both tables just before writing them, or to write
  one catalog file per game.

## Entry format

```
## K1 · Short title

- Where: file and line
- What: what goes wrong, and when
- Fix: the fix, or the plan for it
```
