# Known issues

Bugs and design mistakes found in DinkData's code. Check this file before working in an area,
and add an entry when you find a new one. When an issue is fixed, set its status to Fixed and
link the PR. Don't delete entries.

The prototype's problems are summarised in ADR 0001.

| ID | Area | Problem | Severity | Status |
|---|---|---|---|---|
| K1 | CI | The gitleaks pre-commit hook scans only staged changes, so in CI it checks nothing | Medium | Open |
| K2 | Video | On macOS, OpenCV and PyAV each bundle FFmpeg, and importing both prints duplicate-class warnings | Low | Open |

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

## Entry format

```
## K1 · Short title

- Where: file and line
- What: what goes wrong, and when
- Fix: the fix, or the plan for it
```
