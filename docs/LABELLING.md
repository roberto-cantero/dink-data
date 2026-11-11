# Labelling

How to make each label set. Labels are files that point into the unchanged video by frame and
timestamp. `docs/DESIGN.md` section 9 explains why each set exists, and ADRs 0011 and 0013
record the decisions.

## Label sets

| Set | Purpose | Size | Tool |
|---|---|---|---|
| Full-event gold | Measure events and per-player stats. Never trains | 12 games: 4 dev, 8 test from held-out facilities, split 6 each | Studio events mode, from M1 |
| Rally-level gold | Measure rally winners, serve states, game boundaries and reel clip edges, and how often players break the serving rules | About 50 more games: 20 dev, 30 test | Minimal rally labeller, from M0 |
| Ball clicks | Train the ball tracker (about 4,000 frames) and measure it (about 1,000 test frames) | 2-second clips | CVAT, from M0 |
| Foot clicks | Measure foot position error | About 200 test serve frames | Studio |
| Silver | Train the event spotter | About 10 corrected training games in M3, then beta corrections | Studio |
| Agreement game | Measure how well two people agree | One of the 4 dev games, labelled by both owners | Studio |

Every save goes to a versioned path with the labeller's name, such as
`labels/gold-events/<video_id>/<name>/v<n>.json`. Nothing is overwritten.

## Rules for every label

- Label what happened on court, including the players' own rule breaks. Mark a rule break as a
  rule deviation instead of correcting it.
- Use the player id convention: p1 is the first server in the recording, p2 is p1's partner,
  p3 receives the first serve and p4 is p3's partner.
- If you can't see something, mark it as not visible. Never guess.

## Rally-level gold, about 10 minutes a game

Use the studio's rally mode, a local web page. Get the video's id with
`uv run --env-file .env dink id video`, and save the video as `data/videos/<video_id>.mp4`,
the same name it has in R2. Then open it by id, so no file name reaches your shell history:

```
uv run dink studio --rallies <video_id> --labeller <your handle>
```

1. Press G where the first game starts.
2. Press C and click p1, p2, p3 and p4 once each. The page keeps a crop of each player beside
   the timeline, so you can tell partners apart later. Crops are saved next to your
   labels and uploaded with them to R2, never to the repo.
3. Play the game. At each serve press S, the server (1 to 4) and the side they stand on
   (L or R).
4. When the ball is dead, press E, then A or B for the team that won the rally, or P for a
   replay. Every rally needs a winner, except a last rally the recording cuts off. Players often break the serving rules, so the page
   never decides a winner from the next serve. It only checks yours against it.
5. A red rally doesn't fit the rules. Fix your marks, or press D and pick the rule deviation
   the players made. The page suggests one when it can.
6. Press G where the game ends, or Shift+G if the recording cut it off. Pick the target if it
   isn't 11.
7. Save with the Save button or Cmd+S. The server checks the file against the contract and
   writes `labels/gold-rallies/<video_id>/<handle>/v<n>.json`. Each save is a new version.

The page shows the score as played so you can spot rule breaks. The score and deviations stay
in the gold labels, where they measure how often players get the score wrong, and never reach
a player (ADR 0019). The page stores times in seconds, not frames (ADR 0015). Files saved before 21 October 2026
use `dinkdata.rallies/v1` and no longer load. Run `uv run dink contracts upgrade-rallies` to
save each one as a new v2 version, then re-check every winner, because v1 filled many in from
the next serve. Label only side-out games for now. The labeller can't record a rally-scoring
game yet, so skip one and tell both owners. Python owns every rule: the score
replay is `dinkdata.serves.replay`, and the checks and the file are `dinkdata.studio.rally`.

## Ball clicks in CVAT

Clips are 2 seconds long (60 frames) and come from training or test games. CVAT never gets
the MP4, because it numbers and decodes frames its own way, which broke the prototype's labels.
`dink ball clip` decodes the frames with our reader and saves each one as a JPEG named by its
real frame number, with a `manifest.json` that the converter uses to map CVAT's frames back.
A test in `tests/ball/test_cvat.py` checks that converted frames line up with the video across
dropped frames.

### Set up CVAT once

Run CVAT on your Mac with Docker Desktop, or use CVAT's cloud plan.

```bash
git clone https://github.com/cvat-ai/cvat
```

Before the first start, save this as `docker-compose.override.yml` in the `cvat` folder. It
keeps CVAT on your own Mac, so no one else on the network can reach the frames. It also runs
CVAT's server images under Rosetta, because CVAT publishes them for Intel only.

```yaml
x-intel: &intel
  platform: linux/amd64

services:
  traefik:
    ports: !override
      - 127.0.0.1:8080:8080
      - 127.0.0.1:8090:8090
  cvat_ui: *intel
  cvat_server: *intel
  cvat_worker_annotation: *intel
  cvat_worker_chunks: *intel
  cvat_worker_consensus: *intel
  cvat_worker_export: *intel
  cvat_worker_import: *intel
  cvat_worker_quality_reports: *intel
  cvat_worker_utils: *intel
  cvat_worker_webhooks: *intel
```

Then, inside the `cvat` folder, start it and make your account. The first start downloads a
few GB:

```bash
docker compose up -d
```

```bash
docker exec -it cvat_server bash -ic 'python3 ~/manage.py createsuperuser'
```

Open http://localhost:8080 and sign in. Use `localhost`, because CVAT answers `127.0.0.1`
with "404 page not found". Create a project named `ball` with one label, `ball`, of type
Points. Every task goes in this project.

### Make a clip

Save the video as `data/videos/<video_id>.mp4`. Take the split from the game's catalog row.
Pick a start frame inside a rally, for example from your rally labels.

```bash
uv run dink ball clip <video_id> --start <frame> --split train
```

It writes `data/cvat/<video_id>_f<start>/`, which git ignores, and prints the task name.

### Click the ball

1. In the `ball` project, create a task. Give it the exact name the clip command printed.
   The converter refuses an export whose task name doesn't match the clip folder.
2. Upload every `frame_*.jpg` in the clip folder, not `manifest.json`. Under Advanced, keep
   sorting as Lexicographical and leave start frame, stop frame and frame step empty.
3. Open the job. Draw a points shape with 1 point as a Track, on the ball's centre.
4. In a smooth flight you may click every few frames. CVAT fills the frames between along a
   straight line. Check each filled frame and click again where it is off.
5. When the ball leaves the picture or is hidden, press O on that frame to mark the track
   outside. If you can't see the ball, mark it outside. Never guess. When it comes back, draw a
   new track or switch outside off.
6. Keep one ball track on screen at a time. The converter refuses a frame with two balls.

### Export and convert

1. Export the task with Actions, then Export task dataset, in the "CVAT for video 1.1" format,
   without images.
2. Convert it:

   ```bash
   uv run dink ball convert data/cvat/<video_id>_f<start> <export.zip> --labeller <handle>
   ```

   It writes `labels/ball/<video_id>/<handle>/v<n>.parquet` with one row for every frame of
   the clip. A clicked frame has `clicked` true. A frame CVAT filled has `clicked` false. A
   frame marked outside, or with no ball, is not visible.
3. Each conversion is a new version that holds the latest version's rows plus this clip's.
   Converting a fixed clip again replaces that clip's rows in the new version. Older versions
   stay as they are.
4. Upload with the `rclone copy labels` command in `docs/DATA.md`.

## Calibrating a camera, about 2 minutes

1. Run `dink calibrate <camera_id>` to open a clear frame with no players near the lines.
2. Click every visible keypoint. Skip one that isn't visible.
3. Click 3 to 5 points along each visible line, and the net top at both sidelines and the
   centre.
4. Check that the fitted court sits on the painted lines and that the reprojection error is
   under the threshold.
5. Set the camera setup (down-the-line low, down-the-line high or diagonal) and save.

## Full-event gold, 3 to 5 hours a game

Use the studio's events mode.

1. Calibrate the camera first if needed.
2. Rally pass at 2× speed: press R at each serve contact and again when the ball is dead.
3. Event pass, frame by frame:
   - H then a player number at each contact;
   - B then a click at each bounce, or X if the bounce is out of view;
   - N for the net.
4. Confirm the proposed end reason and winner of each rally.
5. The studio flags any rally where the score doesn't fit the rules. Mark it as a rule
   deviation if the players really did it, otherwise fix your labels.
6. Save.

Start with 2 dev and 2 test games so the eval has data early, then continue to 12.

## Agreement

Both owners label the same dev game separately. `dink eval agreement` compares the two labels.
The hit and bounce targets come from it.
