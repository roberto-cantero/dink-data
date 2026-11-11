# Known issues

Bugs and design mistakes found in DinkData's code. Check this file before working in an area,
and add an entry when you find a new one. When an issue is fixed, set its status to Fixed and
link the PR. Don't delete entries.

The prototype's problems are summarised in ADR 0001.

| ID | Area | Problem | Severity | Status |
|---|---|---|---|---|
| K1 | CI | The gitleaks pre-commit hook scans only staged changes, so in CI it checks nothing | Medium | Open |
| K2 | Video | On macOS, OpenCV and PyAV each bundle FFmpeg, and importing both prints duplicate-class warnings | Low | Open |
| K3 | Data | Two people running `dink ingest` at the same time can lose catalog and id-map rows | Medium | Fixed (#79) |

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

- Where: `src/dinkdata/data/ingest.py`. `ingest` reads the catalog and id map at lines 176-177
  and writes them at lines 223 and 241. `choose_split` is at line 102.
- What: ingest reads `catalog/catalog.parquet` and `catalog/id_map.parquet` when it starts and
  overwrites both when it ends, a few minutes later. If another ingest writes them in between,
  its new rows are lost. The video and its frames stay in R2, but the game has no catalog row,
  and its id-map row may be gone too. Lost rows also break `choose_split`, which takes a game's
  split from its facility's catalog rows. If the lost row was the facility's only one, the next
  ingest from that facility looks like a new facility and accepts any `--split`. A test
  facility's games could then land in dev or train.
- Fix: fixed for #79. Ingest now updates each catalog file with a conditional write through
  boto3. It reads the file and its ETag, adds its row to what it read, and writes only if the
  ETag is unchanged (`If-Match`), or only if the file is still missing (`If-None-Match: *`).
  When another ingest wrote first, R2 refuses the write and ingest reads again, up to 5 times.
  The split check runs again on each try, so the second of two first ingests from a new
  facility fails with the split error instead of giving the facility a second split.
  `dink catalog sync` (#37) must write the catalog the same way.

## Entry format

```
## K1 · Short title

- Where: file and line
- What: what goes wrong, and when
- Fix: the fix, or the plan for it
```
