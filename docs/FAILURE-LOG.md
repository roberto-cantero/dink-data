# Failure log

Known bugs and design mistakes, kept by the team. Check here before working in
an area. When you find a new one, add a row and a section. When it is fixed,
set Status to **Fixed** and link the PR. Don't delete entries; they explain why
the code looks the way it does.

Found in the review of the prototype at commit `e808fd6` (Jul 19, 2025).

| ID | Area | Problem | Severity | Status |
|---|---|---|---|---|
| F1 | utils | Import crashes on a fresh clone | Blocker | Open |
| F2 | all | Windows-only file paths | Blocker | Open |
| F3 | deps | `requirements.txt` doesn't match the code | Blocker | Open |
| F4 | data | Train and test rallies come from the same matches | High | Open |
| F5 | court | Airborne ball projected onto the court | High | Open (code disabled) |
| F6 | rallies | Speeds measured in pixels | High | Open |
| F7 | rallies | Hand-tuned pixel thresholds per video | Medium | Open |
| F8 | court | Calibration click order mislabelled | High | Open |
| F9 | rallies | Highlight end buffer uses the start buffer value | Low | Open |
| F10 | labels | CVAT frame offsets depend on task order | Check | Open |
| F11 | repo | No tests, no CI, `test.py` in `.gitignore` | Medium | Open |

## F1 · Import crashes on a fresh clone

- **Where:** `utils/general.py:24-26`
- **What:** loads `keypoints\court_base.png` and `keypoints\homography.npy` at
  import time. `keypoints/` was never committed, so `cv2.imread` returns `None` and
  `.shape` fails. Every script imports `utils.general`, so nothing runs.
- **Fix:** load calibration only inside the function that needs it, from a path argument.

## F2 · Windows-only file paths

- **Where:** `predict.py:88` (`video_file.split('\\')`), `utils/general.py:24-26`,
  paths in `rally_segmentation.ipynb`
- **What:** backslash paths break on macOS, Linux and cloud GPU workers.
- **Fix:** use `pathlib.Path` everywhere.

## F3 · `requirements.txt` doesn't match the code

- **Where:** `requirements.txt:7` (`torch==1.10.0`) vs `train.py:220`
- **What:** `torch.load(..., weights_only=False)` needs a much newer torch than 1.10.
  The pins can't install a working environment.
- **Fix:** move to torch 2.x and lock dependencies (planned: `uv`).

## F4 · Train and test rallies come from the same matches

- **Where:** `preprocess.py:51-93`
- **What:** validation and test sets are the last rallies of each training match
  (`video_files[-1]`). Same court, lighting and players as training, so accuracy
  numbers are optimistic.
- **Fix:** hold out whole matches, ideally a whole court, for testing.

## F5 · Airborne ball projected onto the court

- **Where:** `utils/general.py:634` (`make_inset`); the call at line 338 is commented out
- **What:** maps every ball position through the floor homography. That is only
  correct when the ball touches the ground. In flight it lands on the minimap far
  from its real position.
- **Fix:** project only bounces (and player feet). See `docs/COURT.md`.

## F6 · Speeds measured in pixels

- **Where:** `rally_segmentation.ipynb` (`SPEED_THRESHOLD = 5` px/frame),
  `rally_segment_features.py` (`AvgSpeed`, `TotalDist_px`)
- **What:** a far-court ball moves fewer pixels than a near-court ball at the same
  speed, so the far side always looks slower and rallies there get cut short.
- **Fix:** measure in court units once bounces and calibration exist.

## F7 · Hand-tuned pixel thresholds per video

- **Where:** `rally_segmentation.ipynb` (`NET_Y_UPPER = 145`, `NET_Y_LOWER = 300`,
  segment lengths and gaps)
- **What:** tuned for one video; wrong for any other camera position.
- **Fix:** take the net line from the calibration; express gaps in seconds using the video's fps.

## F8 · Calibration click order mislabelled

- **Where:** `keypoint_test.py:13-17` (docstring) vs `dst_layout()` at lines 33-55
- **What:** from point 5 on, the docstring's order doesn't match the template the
  code fits to. It lists "far-right kitchen" where the code expects far-left
  kitchen, and skips a point. The window only says "Click point N/12", so following
  the docstring produces a wrong homography.
- **Fix:** replace with 4 corner clicks fitted to the full template (see
  `docs/COURT.md`), and name each point in the prompt.

## F9 · Highlight end buffer uses the start buffer value

- **Where:** `rally_segmentation.ipynb`
  (`EndFrameWithBuffer = EndFrame + SEGMENT_START_BUFFER`)
- **What:** should add `SEGMENT_END_BUFFER` (10 frames); adds 60 instead, so
  highlight clips run 50 frames long.
- **Fix:** use `SEGMENT_END_BUFFER`.

## F10 · CVAT frame offsets depend on task order

- **Where:** `create_gt_csv.py` (`start_frame_actual` in `parse_tracks`)
- **What:** each task's start frame is the running total of earlier task sizes,
  in the order tasks appear in the XML. This is only correct if the export lists
  tasks in the same order their frames were joined. Not verified. `parse_tasks`
  is also defined twice (lines 7 and 28).
- **Fix:** check against one exported project; overlay labels on frames to confirm.

## F11 · No tests, no CI, `test.py` in `.gitignore`

- **Where:** repo root, `.gitignore:27`
- **What:** no automated checks. `test.py` (the evaluation script) is tracked but
  also listed in `.gitignore`, so a new `test.py` elsewhere would be silently ignored.
- **Fix:** add `tests/` with pytest and a CI workflow; rename the eval script when porting.
