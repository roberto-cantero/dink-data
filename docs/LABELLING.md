# Labelling

How to make each label set. Labels are files that point into the unchanged video by frame and
timestamp. `docs/DESIGN.md` section 9 explains why each set exists, and ADRs 0011 and 0013
record the decisions.

## Label sets

| Set | Purpose | Size | Tool |
|---|---|---|---|
| Full-event gold | Measure events and per-player stats. Never trains | 12 games: 4 dev, 8 test from held-out facilities, split 6 each | Studio events mode, from M1 |
| Rally-level gold | Measure the score, game boundaries, rule deviations and reel clip edges | About 50 more games: 20 dev, 30 test | Minimal rally labeller, from M0 |
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

Use the minimal rally labeller, a local web page.

1. Open the recording and play it.
2. At each serve, press the serve key, then pick the server and the side they serve from.
3. When the ball is dead, press the end key. Then pick the winning team, or mark a replay.
4. Mark where each game starts and ends, whether the last game was cut off, and any rule
   deviation, such as the wrong partner serving.
5. Save. The tool stores times in seconds, not frames (ADR 0015). It checks the file against the contract and shows the score it computes, so
   you can compare it with the score the players played.

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
