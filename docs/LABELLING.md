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

1. Open the clip task in CVAT. Clips are 2 seconds long and come from training or test games.
2. Click the ball centre in each frame, or mark the ball hidden.
3. In a smooth flight you may click every few frames and let CVAT fill the frames between,
   then check them.
4. Export. The converter turns the export into `ball_labels.parquet` and its test confirms
   that frame numbers line up with the video.

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
