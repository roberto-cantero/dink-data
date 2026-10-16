# Court geometry

How the pipeline describes the court, maps the video onto it, and what that
mapping can and can't be trusted for. Every module that uses court positions
follows this file.

## Court dimensions

Standard pickleball court (USA Pickleball rules). All values in feet unless noted.

| Item | Value |
|---|---|
| Court width (sideline to sideline) | 20 ft |
| Court length (baseline to baseline) | 44 ft |
| Net to kitchen (non-volley zone) line | 7 ft, each side |
| Net height | 36 in at the sidelines, 34 in at the centre |
| Line width | 2 in |

Lines are part of the area they mark, so a ball touching a line is in, with one
exception: a serve that touches the kitchen line is a fault.

## Coordinate system

Court coordinates are in feet, seen from above:

- **Origin:** the far-left baseline corner, as seen from the camera.
- **x:** 0 to 20, left to right across the court.
- **y:** 0 to 44, from the far baseline toward the camera.
- **Far side** = y < 22, **near side** = y > 22.

```
            x=0        x=10        x=20
   y=0   +-----------+-----------+   far baseline
         |           |           |
         |   far service courts  |
         |           |           |
   y=15  +-----------+-----------+   far kitchen line
         |      far kitchen      |
   y=22  +=======================+   net
         |      near kitchen     |
   y=29  +-----------+-----------+   near kitchen line
         |           |           |
         |  near service courts  |
         |           |           |
   y=44  +-----------+-----------+   near baseline (camera end)
```

This matches the template in the prototype's `keypoint_test.py`, which draws the
court at 20 px per foot. That scale is for drawing only; store positions in feet.

> **To agree:** both partners confirm this system before `contracts/court.schema.json`
> is frozen. Changing it later touches every file.

## Court keypoints

The 12 template points, in court feet. Calibration matches image points to some or all of these.

| Name | x | y |
|---|---|---|
| far_left_corner | 0 | 0 |
| far_right_corner | 20 | 0 |
| near_right_corner | 20 | 44 |
| near_left_corner | 0 | 44 |
| far_kitchen_left | 0 | 15 |
| far_kitchen_right | 20 | 15 |
| near_kitchen_right | 20 | 29 |
| near_kitchen_left | 0 | 29 |
| far_kitchen_centre | 10 | 15 |
| near_kitchen_centre | 10 | 29 |
| far_baseline_centre | 10 | 0 |
| near_baseline_centre | 10 | 44 |

Name points in code by these names, never by index. Mixing up indexes is
failure F8 in `docs/FAILURE-LOG.md`.

## Camera setups and video format

Every video is 1080p at a nominal 30 fps, shot on a different camera. Some videos
have dropped or unstable frame rates, so convert frames to seconds with frame
timestamps, not a fixed 30. Videos time out at 45 minutes and end automatically,
so a game can stop mid-rally.

| Setup | Share of videos | Notes |
|---|---|---|
| Down-the-line (DTL), low (2 m or below) | ~64% (80% x 80%) | Most common. Steep foreshortening: far-court players and ball are small, and players occlude each other |
| DTL, high (above 2 m) | ~16% (80% x 20%) | Better view of the floor; less occlusion |
| Slight diagonal | ~20% | Used when court restrictions block the DTL spot. The court is skewed in the image, so don't assume the net is horizontal |

DTL means centred on the back wall, looking down the centre line. Shares are
approximate. Eval sets must include all three setups.

## Calibration

The homography maps image pixels to court feet on the ground plane.

1. **Input:** at least the 4 corners. More keypoints (kitchen and centre points)
   make the fit more robust; fit with RANSAC.
2. **Check:** project all 12 template points back into the image. Mean
   reprojection error should stay under `FILL-IN` px at 1080p. Reject the
   calibration if it doesn't.
3. **Store** it in `court.json` with the camera id, the image size it was made at,
   the error, and whether it was manual or automatic.
4. **Reuse** it only for videos known to come from the same fixed camera in the
   same position. Cameras differ between videos, so by default calibrate each video.
   Recalibrate if the camera is moved or bumped, or if the reprojection check
   on a new video's first frame fails.

Kitchen lines and the net don't need their own clicks: once the homography is
fitted, project their court coordinates back into the image.

## What the homography can be trusted for

It describes the floor only.

| Use | OK? | Why |
|---|---|---|
| Player position | Yes | Use the foot point: the bottom centre of the player's box, or the midpoint of the ankles from pose |
| Ball bounce position | Yes | The ball is on the floor at that moment |
| Ball position in flight | **No** | The ball is above the floor, so the projection lands in the wrong place, often by several feet |
| Which side of the net the ball is on | Only at bounces or hits | Between them, infer from the bounce and hit sequence |
| Ball height, ball speed | **No** | Needs a 3D estimate (P3); label any result as approximate |

## Zones used by stats

| Zone | Rule (court feet) |
|---|---|
| In court | 0 ≤ x ≤ 20 and 0 ≤ y ≤ 44 |
| Far kitchen | 15 ≤ y ≤ 22 |
| Near kitchen | 22 ≤ y ≤ 29 |
| Service court | the box diagonal from the server, between the kitchen line and the baseline, split at x = 10 |
| At the kitchen line | foot point within `FILL-IN` ft of the player's own kitchen line (proposal: 2 ft) |
| Close call | bounce within `FILL-IN` in of any line (proposal: 6 in). Flag for review instead of calling it |

Line width matters near the edges: a 2 in line is about 0.17 ft. Treat a bounce
whose position is within the line's width plus the calibration error as a close call.

## Open questions

- [x] Typical mount: ~80% DTL on the back wall, ~20% slight diagonal; of the DTL, ~80% at 2 m or below. See "Camera setups and video format".
- [ ] Does the camera ever sit behind the other baseline within one match, or do the far/near ends swap?
- [ ] Reprojection error threshold, set from the first real calibrations.
- [ ] Are all four corners always visible in PickleCam footage? If not, which keypoints can stand in?
