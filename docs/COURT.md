# Court geometry and calibration

How the pipeline describes the court, maps video onto it, and what that mapping can be
trusted for. Code in `src/dinkdata/court/` follows this file. `docs/DESIGN.md` section 6.3 has
the reasoning, and ADR 0004 records the decision.

## Court dimensions

USA Pickleball rules, in feet.

| Item | Value |
|---|---|
| Court width | 20 ft |
| Court length | 44 ft |
| Net to kitchen line | 7 ft on each side |
| Net height | 36 in at the sidelines, 34 in at the centre |
| Line width | 2 in |

A ball touching a line is in, except a serve touching the kitchen line, which is a fault.

## Coordinates

![Court coordinates](diagrams/court.svg)

- The origin is the far-left baseline corner as seen from the camera. For a diagonal
  camera, "far" means the baseline farther from the camera.
- x runs from 0 to 20 across the court. y runs from 0 to 44 toward the camera.
- The net is at y = 22. The kitchen lines are at y = 15 and y = 29.
- Positions are stored in feet. A position the camera can't see is `null`.

## Keypoints

Calibration matches clicked image points to these named points. Code names them and never
numbers them.

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
| net_top_left | 0 | 22, height 3 ft |
| net_top_centre | 10 | 22, height 2.83 ft |
| net_top_right | 20 | 22, height 3 ft |

## Calibration

1. A person clicks the visible keypoints, 3 to 5 points along each visible line, and the
   net tops.
2. The solver fits a pinhole camera with radial distortion (k1, k2) using
   `scipy.optimize.least_squares` with a robust loss. Net heights are soft constraints,
   because rec nets can sag.
3. Lens parameters are fitted jointly across cameras of the same model. Each camera gets
   its own pose and a small distortion correction.
4. The mean reprojection error on held-back clicks must stay under a threshold, set from
   the first 20 calibrations.
5. The visibility mask is the image border projected onto the floor, clipped at the horizon.
6. The result is saved as `cameras/{camera_id}/v{n}/camera.json`. A new calibration is a new
   version, and old versions are never overwritten.
7. From M1, every video's background is compared with the projected court lines. A
   mismatch flags the camera as moved.

## What the mapping can be trusted for

| Use | Allowed | Reason |
|---|---|---|
| Player foot position | Yes | The foot is on the floor |
| Ball bounce position | Yes | The ball touches the floor |
| Ball in flight | No | The ball is above the floor, so the projection lands in the wrong place |
| Ball height or speed | No | Needs a 3D estimate, which v1 doesn't have |

## Zones

| Zone | Rule |
|---|---|
| In court | 0 ≤ x ≤ 20 and 0 ≤ y ≤ 44 |
| Far kitchen | 15 ≤ y ≤ 22 |
| Near kitchen | 22 ≤ y ≤ 29 |
| Service court | The box diagonal from the server, between the kitchen line and the baseline, split at x = 10 |
| Close call | A bounce within the line width plus the calibration error of a line. Flagged for review |
