"""The calibration solver: clicks in, `camera.json` v1 out (docs/COURT.md, DESIGN 6.3, ADR 0020).

`solve` fits a pinhole camera to a `camera_clicks/v1` record. The camera has one focal length
(fx = fy), the principal point at the image centre, radial distortion k1 and k2, and a
6-degree-of-freedom pose: 9 parameters. Each net top adds its own height, held near the
rule-book height by a soft prior, because rec nets sag.

The fit starts from a floor homography of the keypoints and runs
`scipy.optimize.least_squares` with a `soft_l1` loss. Every residual is in pixels:

- each floor keypoint and net top gives its pixel error;
- each line point gives its signed distance to the projected court line;
- each net top height, and the focal length, k1 and k2, give a prior residual. One sigma off
  a prior costs as much as a click `PRIOR_PX` image heights off.

People click the centre of a painted line, so keypoints and lines sit at the line centres from
`line_centre`, 1 in inside docs/COURT.md's boundaries.

The held-back error is the mean leave-one-out error over the floor keypoints: each keypoint is
refit without itself and measured. The solver refuses a fit it can't trust, with an error that
names the cause. Every constant here is provisional, and #50 tunes them on real cameras.
Constants in pixels are shares of the image height, so none is hardcoded for one video size.

scipy is imported inside the functions, so this module imports without the `cv` extra.
"""

from dataclasses import dataclass, field
from itertools import combinations

import numpy as np

from dinkdata.contracts.camera import CameraCalibration
from dinkdata.contracts.camera_clicks import CameraClicks, CourtLine, FloorKeypoint, NetTop
from dinkdata.contracts.common import CameraSetup
from dinkdata.court.floor import image_to_court, max_radius, rotation, undistort
from dinkdata.court.keypoints import COURT_LINE_ENDS, KEYPOINTS
from dinkdata.court.zones import FAR_KITCHEN_Y, LENGTH, NEAR_KITCHEN_Y, NET_Y, WIDTH

LINE_HALF_WIDTH_FT = 1 / 12
"""Half of a painted line's 2 in width. A line's centre is this far inside its boundary."""

ROBUST_SCALE = 0.002
"""The `soft_l1` loss scale, in image heights: about 2 px at 1080p. Provisional."""
PRIOR_PX = 0.001
"""How far off, in image heights, a click costs as much as one sigma off a prior. Provisional."""
NET_SAG_SIGMA_FT = 2 / 12
"""How far a net top may sag or stand above its rule-book height, as one sigma. Provisional."""
FOCAL_PRIOR = 0.55
"""The focal length the weak prior expects, in image widths. Provisional."""
FOCAL_PRIOR_LOG_SIGMA = 0.5
"""One sigma of the focal length prior, as a natural log ratio. Weak. Provisional."""
K1_PRIOR_SIGMA = 0.5
"""One sigma of the prior that holds k1 near 0. Weak. Provisional."""
K2_PRIOR_SIGMA = 0.5
"""One sigma of the prior that holds k2 near 0. Weak. Provisional."""

MIN_KEYPOINTS = 4
"""The fewest floor keypoints a fit needs, with no 3 on one line among some 4 of them."""
MIN_HELD_BACK_LINES = 2
"""A refit with one keypoint fewer than MIN_KEYPOINTS needs line points on this many lines."""
MAX_EVALUATIONS = 2000
"""The most residual evaluations one robust fit may take before it counts as failed."""
PLAIN_MAX_EVALUATIONS = 200
"""The most evaluations a plain pass from a start may take. Good ones converge in under 10, so
a start that needs more is bad, and failing fast lets the other start run. Provisional."""
FOLD_MARGIN = 0.05
"""During the fit, the lens must keep growing this share past the farthest click. Provisional."""
UNDISTORT_STEPS = 20
"""Newton steps when undistorting a line point during the fit. Converges well inside the fold."""

DOWN_THE_LINE: frozenset[CameraSetup] = frozenset({"dtl_low", "dtl_high"})

VISIBLE_MARGIN_FT = 10.0
"""The visibility mask reaches this far beyond the court's lines on every side."""
BORDER_SAMPLES = 128
"""Samples per image side when projecting the image border onto the floor."""
FOLD_INSET = 1e-4
"""The visibility mask stops this share of the fold radius inside a fold within the image."""


class CalibrationError(ValueError):
    """The solver refuses these clicks. The message names the cause and what to fix."""


class TooFewKeypoints(CalibrationError):
    """Fewer than MIN_KEYPOINTS floor keypoints."""


class CollinearKeypoints(CalibrationError):
    """No MIN_KEYPOINTS of the floor keypoints are free of 3 on one line."""


class HeldBackErrorUndefined(CalibrationError):
    """A leave-one-out refit would have too little to fit, so the held-back error is undefined."""


class CameraBelowFloor(CalibrationError):
    """The fitted camera is on or below the floor, which usually means swapped names."""


class CameraBeyondNet(CalibrationError):
    """The fitted camera is on the far side of the net, which usually means swapped names."""


class FoldingLens(CalibrationError):
    """The fitted lens stops growing inside the image, so its undistortion folds there."""


class FitDidNotConverge(CalibrationError):
    """The least-squares fit stopped before it converged."""


@dataclass(frozen=True)
class CalibrationFit:
    """A fitted calibration with what the click tool shows beside it."""

    camera: CameraCalibration
    held_back_px: dict[FloorKeypoint, float]
    """Each floor keypoint's error, in pixels, when the camera is refit without it."""
    warnings: list[str] = field(default_factory=list)


def line_centre(point: tuple[float, float]) -> tuple[float, float]:
    """Move a docs/COURT.md boundary point to the centre of the painted line it sits on.

    The sidelines and baselines lie inside the court, and each kitchen line inside its kitchen,
    so their centres are 1 in inside the boundary. The centre line stays at x = 10, so a
    `*_centre` keypoint moves along y only. The net's line at y = 22 doesn't move.
    """
    x, y = point
    h = LINE_HALF_WIDTH_FT
    x_moves = {0.0: h, WIDTH: -h}
    y_moves = {0.0: h, FAR_KITCHEN_Y: h, NEAR_KITCHEN_Y: -h, LENGTH: -h}
    return (x + x_moves.get(x, 0.0), y + y_moves.get(y, 0.0))


def solve(clicks: CameraClicks, *, setup: CameraSetup) -> CalibrationFit:
    """Fit `camera.json` v1 to the clicks, or raise a `CalibrationError` that names the cause.

    `setup` is the camera setup the person picked. It is saved in the calibration and decides
    whether a missing net top gets a warning. The result's `reprojection_error_px` is the mean
    of `held_back_px`.
    """
    problem = _Problem.from_clicks(clicks)
    problem.check_enough_keypoints()

    params = _best_fit(problem)
    camera = _calibration(clicks, setup, params, error_px=0.0)
    _check_camera(camera, farthest_px=problem.farthest_px)

    held_back: dict[FloorKeypoint, float] = {}
    for n, name in enumerate(problem.keypoint_names):
        without = problem.without_keypoint(n)
        refit, _ = _fit(without, params, what=f"the refit without {name}")
        pixel = _project(refit, problem.keypoint_court[n : n + 1], problem.image_size)[0]
        held_back[name] = float(np.linalg.norm(pixel - problem.keypoint_px[n]))

    error = float(np.mean(list(held_back.values())))
    record = camera.model_dump(by_alias=True)
    record.update(reprojection_error_px=error, visible_region=visible_region(camera))
    camera = CameraCalibration.model_validate(record)

    warnings: list[str] = []
    if setup in DOWN_THE_LINE and not clicks.net_tops:
        warnings.append(
            "This down-the-line camera has no net tops, so its focal length is poorly fixed. "
            "Click the net tops if they are in view."
        )
    return CalibrationFit(camera=camera, held_back_px=held_back, warnings=warnings)


def visible_region(camera: CameraCalibration) -> list[tuple[float, float]]:
    """The floor the camera sees, as a polygon in court feet.

    The image border, sampled densely, is projected onto the floor. Where the lens folds inside
    the image, the border is pulled in to just inside the fold. A border pixel at or above
    the horizon, or one whose floor point is very far away, stops short at a distance beyond
    the clipping box, so the clip cuts it off. The polygon is clipped to VISIBLE_MARGIN_FT
    beyond the court's lines.
    """
    w, h = camera.image_size.width, camera.image_size.height
    s = np.linspace(0.0, 1.0, BORDER_SAMPLES, endpoint=False)
    border = np.concatenate(
        [
            np.column_stack([s * w, np.zeros_like(s)]),
            np.column_stack([np.full_like(s, w), s * h]),
            np.column_stack([(1 - s) * w, np.full_like(s, h)]),
            np.column_stack([np.zeros_like(s), (1 - s) * h]),
        ]
    )
    box = (
        -VISIBLE_MARGIN_FT,
        WIDTH + VISIBLE_MARGIN_FT,
        -VISIBLE_MARGIN_FT,
        LENGTH + VISIBLE_MARGIN_FT,
    )

    rot = rotation(camera.rotation)
    centre = -rot.T @ np.asarray(camera.translation)
    corners = np.array([[box[0], box[2]], [box[1], box[2]], [box[1], box[3]], [box[0], box[3]]])
    far = 4 * float(np.max(np.linalg.norm(corners - centre[:2], axis=1)))

    # Past the fold the lens maps nowhere, so the border is pulled in to just inside it.
    image_centre = np.array([w / 2, h / 2])
    offset = border - image_centre
    reach_px = np.linalg.norm(offset, axis=1)
    limit = fold_radius_px(camera) * (1 - FOLD_INSET)
    border = image_centre + offset * np.minimum(1.0, limit / np.maximum(reach_px, 1e-12))[:, None]

    i = camera.intrinsics
    ideal = undistort(camera, (border - np.array([i.cx, i.cy])) / np.array([i.fx, i.fy]))
    rays = np.column_stack([ideal, np.ones(len(ideal))]) @ rot
    floor = image_to_court(camera, border, video_size=(w, h))
    reach = np.linalg.norm(floor - centre[:2], axis=1)
    keep = np.isfinite(reach) & (reach <= far)
    flat = rays[:, :2] / np.linalg.norm(rays[:, :2], axis=1, keepdims=True)
    points = np.where(keep[:, None], floor, centre[:2] + far * flat)
    points = points[np.isfinite(points).all(axis=1)]

    polygon = _clip_to_box(points, box)
    polygon = _drop_redundant(polygon)
    if len(polygon) < 3:
        raise CalibrationError("the fitted camera sees none of the floor near the court")
    return [(float(x), float(y)) for x, y in polygon]


# The problem: clicks matched to court points


@dataclass(frozen=True)
class _Problem:
    image_size: tuple[int, int]
    keypoint_names: list[FloorKeypoint]
    keypoint_court: np.ndarray  # (K, 3) line centres in court coordinates, z down
    keypoint_px: np.ndarray  # (K, 2)
    net_names: list[NetTop]
    net_court: np.ndarray  # (N, 3) with the rule-book height as z = -height
    net_px: np.ndarray  # (N, 2)
    lines: list[tuple[CourtLine, np.ndarray, np.ndarray]]  # name, (2, 3) centre ends, (M, 2) clicks

    @classmethod
    def from_clicks(cls, clicks: CameraClicks) -> "_Problem":
        kp_names = list(clicks.keypoints)
        net_names = list(clicks.net_tops)
        lines: list[tuple[CourtLine, np.ndarray, np.ndarray]] = []
        for name, points in clicks.line_points.items():
            ends = np.array([[*line_centre(p), 0.0] for p in COURT_LINE_ENDS[name]])
            lines.append((name, ends, np.array(points, dtype=float)))
        return cls(
            image_size=(clicks.image_size.width, clicks.image_size.height),
            keypoint_names=kp_names,
            keypoint_court=np.array([_court(n) for n in kp_names]).reshape(-1, 3),
            keypoint_px=np.array([clicks.keypoints[n] for n in kp_names], float).reshape(-1, 2),
            net_names=net_names,
            net_court=np.array([_court(n) for n in net_names]).reshape(-1, 3),
            net_px=np.array([clicks.net_tops[n] for n in net_names], float).reshape(-1, 2),
            lines=lines,
        )

    @property
    def click_radii_px(self) -> np.ndarray:
        """Each click's distance from the image centre, in pixels."""
        clicks = [self.keypoint_px, self.net_px, *(points for _, _, points in self.lines)]
        centre = np.array(self.image_size) / 2
        return np.linalg.norm(np.concatenate(clicks) - centre, axis=1)

    @property
    def farthest_px(self) -> float:
        """The distance of the farthest click from the image centre, in pixels."""
        return float(self.click_radii_px.max())

    def without_keypoint(self, n: int) -> "_Problem":
        keep = [i for i in range(len(self.keypoint_names)) if i != n]
        return _Problem(
            image_size=self.image_size,
            keypoint_names=[self.keypoint_names[i] for i in keep],
            keypoint_court=self.keypoint_court[keep],
            keypoint_px=self.keypoint_px[keep],
            net_names=self.net_names,
            net_court=self.net_court,
            net_px=self.net_px,
            lines=self.lines,
        )

    def check_enough_keypoints(self) -> None:
        count = len(self.keypoint_names)
        if count < MIN_KEYPOINTS:
            raise TooFewKeypoints(
                f"the fit needs at least {MIN_KEYPOINTS} floor keypoints, and these clicks have "
                f"{count} floor keypoints. Click more keypoints."
            )
        floor = self.keypoint_court[:, :2]
        triples = [t for t in combinations(range(count), 3) if _collinear(floor[list(t)])]
        free = any(
            not any(set(t) <= set(four) for t in triples)
            for four in combinations(range(count), MIN_KEYPOINTS)
        )
        if not free:
            names = ", ".join(self.keypoint_names[i] for i in triples[0])
            raise CollinearKeypoints(
                f"no {MIN_KEYPOINTS} of the floor keypoints are free of 3 on one line ({names} "
                "are on one line). Click a keypoint off that line."
            )
        lines = len(self.lines)
        if count - 1 < MIN_KEYPOINTS and lines < MIN_HELD_BACK_LINES:
            raise HeldBackErrorUndefined(
                f"with {count} floor keypoints, each leave-one-out refit has {count - 1}, which "
                f"needs line points on at least {MIN_HELD_BACK_LINES} court lines, and these "
                f"clicks have them on {lines}. The held-back error is undefined. Click points "
                "along the court lines, or another keypoint."
            )

    def residuals(self, params: np.ndarray) -> np.ndarray:
        height = self.image_size[1]
        prior_px = PRIOR_PX * height
        f, k1, k2 = _lens(params, height)
        parts = [
            (_project(params, self.keypoint_court, self.image_size) - self.keypoint_px).ravel()
        ]
        if len(self.net_names):
            heights = params[9 : 9 + len(self.net_names)]
            nets = self.net_court.copy()
            nets[:, 2] = -heights
            parts.append((_project(params, nets, self.image_size) - self.net_px).ravel())
            parts.append((heights + self.net_court[:, 2]) / NET_SAG_SIGMA_FT * prior_px)
        for _, ends, points in self.lines:
            parts.append(_line_distance(params, ends, points, self.image_size))
        # A barrier keeps the lens growing out past every click: each click within FOLD_MARGIN
        # of the fold costs its distance past that line, in pixels. Without it a fit can fold
        # the lens inside the clicks, where the lens is flat and maps nothing well.
        _, fold = _fold(k1, k2)
        parts.append(np.maximum(0.0, self.click_radii_px * (1 + FOLD_MARGIN) - f * fold))
        width = self.image_size[0]
        parts.append(
            np.array(
                [
                    np.log(f / (FOCAL_PRIOR * width)) / FOCAL_PRIOR_LOG_SIGMA,
                    k1 / K1_PRIOR_SIGMA,
                    k2 / K2_PRIOR_SIGMA,
                ]
            )
            * prior_px
        )
        return np.concatenate(parts)


def _court(name: FloorKeypoint | NetTop) -> tuple[float, float, float]:
    x, y, height = KEYPOINTS[name]
    cx, cy = line_centre((x, y))
    return (cx, cy, -height)


def _collinear(points: np.ndarray) -> bool:
    (ax, ay), (bx, by), (cx, cy) = points
    return abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) < 1e-6


# The camera model, on a flat parameter vector:
# rotation vector (3), translation in feet (3), log(f / image height), k1, k2, net top heights.


def _lens(params: np.ndarray, height: int) -> tuple[float, float, float]:
    return float(height * np.exp(params[6])), float(params[7]), float(params[8])


def _fold(k1: float, k2: float) -> tuple[float, float]:
    """The undistorted and distorted radii, in focal lengths, where the lens stops growing.

    The same root as `floor.max_radius`, from k1 and k2 alone, so the fit can use it. Both are
    inf for a lens that never folds.
    """
    if k2 == 0:
        u = -1 / (3 * k1) if k1 < 0 else np.inf
    else:
        disc = 9 * k1 * k1 - 20 * k2
        roots = (
            [] if disc < 0 else [(-3 * k1 + sign * np.sqrt(disc)) / (10 * k2) for sign in (-1, 1)]
        )
        positive = [r for r in roots if r > 0]
        u = min(positive) if positive else np.inf
    if not np.isfinite(u):
        return np.inf, np.inf
    r = float(np.sqrt(u))
    return r, r * (1 + k1 * u + k2 * u * u)


_MIN_DEPTH_FT = 1e-3


def _project(params: np.ndarray, points: np.ndarray, image_size: tuple[int, int]) -> np.ndarray:
    """Court points (z down) to raw pixels. Points behind the camera are pushed in front.

    This is `court_to_image` without the NaNs, so the optimiser always sees finite residuals.
    The fitted camera is checked for a folding lens afterwards.
    """
    width, height = image_size
    f, k1, k2 = _lens(params, height)
    cam = points @ rotation(params[:3]).T + params[3:6]
    depth = np.maximum(cam[:, 2:3], _MIN_DEPTH_FT)
    ideal = cam[:, :2] / depth
    r2 = (ideal**2).sum(axis=1, keepdims=True)
    return f * ideal * (1 + k1 * r2 + k2 * r2 * r2) + np.array([width / 2, height / 2])


def _line_distance(
    params: np.ndarray, ends: np.ndarray, points: np.ndarray, image_size: tuple[int, int]
) -> np.ndarray:
    """Each clicked pixel's signed distance to a projected court line, in pixels.

    A court line and the camera centre span a plane, which meets the undistorted image in a
    straight line. Each click is undistorted and measured against that line, and the distance
    is scaled back to raw pixels by the lens's stretch across the line at the click. This is
    smooth in the parameters, so the optimiser converges cleanly, and it doesn't depend on
    where the line's ends fall, even behind the camera.
    """
    width, height = image_size
    f, k1, k2 = _lens(params, height)
    cam = ends @ rotation(params[:3]).T + params[3:6]
    normal = np.cross(cam[0], cam[1])
    normal = normal / np.linalg.norm(normal[:2])

    # This is `floor.undistort` with a click past the fold held at the fold instead of NaN, so
    # the optimiser always sees finite residuals. The barrier in `residuals` pulls the fold out
    # past such a click, and the fitted lens is checked afterwards.
    distorted = (points - np.array([width / 2, height / 2])) / f
    rd = np.sqrt((distorted**2).sum(axis=1))
    r_max, _ = _fold(k1, k2)
    r = np.minimum(rd, r_max)
    for _ in range(UNDISTORT_STEPS):
        r2 = r * r
        slope = 1 + 3 * k1 * r2 + 5 * k2 * r2 * r2
        step = (r * (1 + k1 * r2 + k2 * r2 * r2) - rd) / np.maximum(slope, 1e-9)
        r = np.clip(r - step, 0.0, r_max)
    scale = np.where(rd > 0, r / np.maximum(rd, 1e-12), 1.0)
    ideal = distorted * scale[:, None]
    gap = ideal @ normal[:2] + normal[2]

    # The lens Jacobian at the undistorted click u is J = d I + b u u^T, with d the radial
    # factor and b = 2 (k1 + 2 k2 r^2). A distance across the line maps through J^-T, and J
    # is symmetric with inverse (I - b u u^T / (d + b r^2)) / d.
    r2 = (ideal**2).sum(axis=1)
    radial = 1 + k1 * r2 + k2 * r2 * r2
    bend = 2 * (k1 + 2 * k2 * r2)
    along = (ideal @ normal[:2]) * bend / np.maximum(radial + bend * r2, 1e-9)
    mapped = (normal[:2] - along[:, None] * ideal) / radial[:, None]
    stretch = np.linalg.norm(mapped, axis=1)
    return f * gap / np.maximum(stretch, 1e-12)


# Fitting


def _initial_guesses(problem: _Problem) -> list[np.ndarray]:
    """Two starts from a floor homography of the keypoints, with no distortion.

    With the principal point known, the homography's first two columns are the court's x and
    y axes in camera coordinates, scaled by 1 / f in x and y. Their being orthogonal and of
    equal length gives f, which is the first start. The homography ignores the lens, so for a
    low camera that sees the court at a grazing angle that f can be far off. The second start
    puts f at the prior and refits the pose at that f.
    """
    from scipy.optimize import least_squares

    width, height = problem.image_size
    pixels = problem.keypoint_px - np.array([width / 2, height / 2])
    hom = _homography(problem.keypoint_court[:, :2], pixels)
    (a1, b1, c1), (a2, b2, c2) = hom[:, 0], hom[:, 1]
    guesses = []
    if abs(c1 * c2) > 1e-12:
        guesses.append(-(a1 * a2 + b1 * b2) / (c1 * c2))
    if abs(c1 * c1 - c2 * c2) > 1e-12:
        guesses.append(-(a1 * a1 + b1 * b1 - a2 * a2 - b2 * b2) / (c1 * c1 - c2 * c2))
    positive = [g for g in guesses if g > 0]
    prior_f = FOCAL_PRIOR * width
    homography_f = float(np.sqrt(np.median(positive))) if positive else prior_f

    first = _pose_from_homography(problem, hom, homography_f)
    second = _pose_from_homography(problem, hom, prior_f)

    def pose_residuals(pose: np.ndarray) -> np.ndarray:
        return problem.residuals(np.concatenate([pose, second[6:]]))

    refit = least_squares(pose_residuals, second[:6], x_scale="jac", max_nfev=PLAIN_MAX_EVALUATIONS)
    if np.isfinite(refit.x).all():
        second[:6] = refit.x
    return [first, second]


def _pose_from_homography(problem: _Problem, hom: np.ndarray, f: float) -> np.ndarray:
    """Parameters with the pose that the homography gives at focal length `f`, and no lens."""
    from scipy.spatial.transform import Rotation

    m = np.diag([1 / f, 1 / f, 1.0]) @ hom
    scale = 2 / (np.linalg.norm(m[:, 0]) + np.linalg.norm(m[:, 1]))
    depth = (problem.keypoint_court[:, :2] @ m[:, :2].T + m[:, 2])[:, 2]
    if np.mean(depth) < 0:
        scale = -scale
    r1, r2, t = scale * m[:, 0], scale * m[:, 1], scale * m[:, 2]
    u, _, vt = np.linalg.svd(np.column_stack([r1, r2, np.cross(r1, r2)]))
    params = np.zeros(9 + len(problem.net_names))
    params[:3] = Rotation.from_matrix(u @ vt).as_rotvec()
    params[3:6] = t
    params[6] = np.log(f / problem.image_size[1])
    params[9:] = -problem.net_court[:, 2]
    return params


def _homography(court: np.ndarray, pixels: np.ndarray) -> np.ndarray:
    """The normalised direct linear transform from floor points to pixels."""

    def normaliser(points: np.ndarray) -> np.ndarray:
        mean = points.mean(axis=0)
        spread = np.sqrt(((points - mean) ** 2).sum(axis=1)).mean() / np.sqrt(2)
        s = 1 / max(spread, 1e-12)
        return np.array([[s, 0, -s * mean[0]], [0, s, -s * mean[1]], [0, 0, 1]])

    tc, tp = normaliser(court), normaliser(pixels)
    c = np.column_stack([court, np.ones(len(court))]) @ tc.T
    p = np.column_stack([pixels, np.ones(len(pixels))]) @ tp.T
    rows = []
    for (x, y, _), (u, v, _) in zip(c, p, strict=True):
        rows.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        rows.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    _, _, vt = np.linalg.svd(np.array(rows))
    hom = np.linalg.inv(tp) @ vt[-1].reshape(3, 3) @ tc
    return hom / np.linalg.norm(hom[:, :2], axis=0).mean()


def _fit(
    problem: _Problem, start: np.ndarray, *, what: str, from_far: bool = False
) -> tuple[np.ndarray, float]:
    """Least squares with the robust loss. Raises `FitDidNotConverge` when it stops early.

    `from_far` marks a start from the homography guess, which can be far off. The robust loss
    has local minima there, so a plain least-squares pass runs first to reach the right basin.
    A refit starts from the full fit, which is already close. Returns the parameters and the
    final robust cost.
    """
    from scipy.optimize import least_squares

    stages = [
        ("linear", 1.0, PLAIN_MAX_EVALUATIONS),
        ("soft_l1", ROBUST_SCALE * problem.image_size[1], MAX_EVALUATIONS),
    ]
    params, cost = start, np.inf
    for loss, scale, cap in stages if from_far else stages[1:]:
        result = least_squares(
            problem.residuals,
            params,
            loss=loss,
            f_scale=scale,
            x_scale="jac",
            max_nfev=cap,
        )
        if result.status <= 0 or not np.isfinite(result.x).all():
            raise FitDidNotConverge(
                f"{what} didn't converge after {result.nfev} evaluations ({result.message}). "
                "Check the clicks for a misplaced or misnamed point."
            )
        params, cost = result.x, float(result.cost)
    return params, cost


def _best_fit(problem: _Problem) -> np.ndarray:
    """Fit from each start and keep the lowest cost. Refuses only when every start fails."""
    fits, failure = [], None
    for start in _initial_guesses(problem):
        try:
            fits.append(_fit(problem, start, what="the fit", from_far=True))
        except FitDidNotConverge as error:
            failure = error
    if not fits:
        assert failure is not None
        raise failure
    return min(fits, key=lambda fit: fit[1])[0]


def _calibration(
    clicks: CameraClicks, setup: CameraSetup, params: np.ndarray, *, error_px: float
) -> CameraCalibration:
    width, height = clicks.image_size.width, clicks.image_size.height
    f, k1, k2 = _lens(params, height)
    return CameraCalibration.model_validate(
        {
            "schema": "dinkdata.camera/v1",
            "camera_id": clicks.camera_id,
            "version": clicks.version,
            "model": None,
            "setup": setup,
            "image_size": {"width": width, "height": height},
            "intrinsics": {"fx": f, "fy": f, "cx": width / 2, "cy": height / 2},
            "distortion": {"k1": k1, "k2": k2},
            "rotation": [float(v) for v in params[:3]],
            "translation": [float(v) for v in params[3:6]],
            "reprojection_error_px": error_px,
            "visible_region": [(0.0, 0.0), (WIDTH, 0.0), (WIDTH, LENGTH)],
            "overlay_masks": [
                [(x0, y0), (x1, y0), (x1, y1), (x0, y1)] for x0, y0, x1, y1 in clicks.overlay_rects
            ],
            "source": "clicks",
        }
    )


def fold_radius_px(camera: CameraCalibration) -> float:
    """How far from the image centre, in raw pixels, the lens stops growing. inf if never.

    The floor functions give NaN past this radius, and the visibility mask stops short of it.
    """
    r = max_radius(camera)
    if not np.isfinite(r):
        return np.inf
    k1, k2 = camera.distortion.k1, camera.distortion.k2
    return float(r * (1 + k1 * r * r + k2 * r**4) * camera.intrinsics.fx)


def _check_camera(camera: CameraCalibration, *, farthest_px: float) -> None:
    """Refuse a camera below the floor, beyond the net, or with a lens that folds in the clicks.

    The lens only has to grow out to the farthest click. Beyond that nothing constrains it,
    and the floor functions give NaN past the fold, so a fold between the clicks and the image
    corner is allowed.
    """
    rot = rotation(camera.rotation)
    x, y, z = -rot.T @ np.asarray(camera.translation)
    if z >= 0:
        raise CameraBelowFloor(
            f"the fit puts the camera {z:.1f} ft below the floor. Names are probably swapped "
            "between left and right or near and far. Check the keypoint names."
        )
    if y < NET_Y:
        raise CameraBeyondNet(
            f"the fit puts the camera at y = {y:.1f} ft, on the far side of the net, so the "
            "court is turned around. Names are probably swapped both between left and right "
            "and between near and far. Check the keypoint names."
        )
    fold = fold_radius_px(camera)
    if fold <= farthest_px:
        k1, k2 = camera.distortion.k1, camera.distortion.k2
        raise FoldingLens(
            f"the fitted lens (k1 = {k1:.3f}, k2 = {k2:.3f}) folds {fold:.0f} px from the image "
            f"centre, inside the clicks, which reach {farthest_px:.0f} px. A click far from the "
            "centre is probably misplaced or misnamed."
        )


# The visibility mask


def _clip_to_box(points: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
    """Sutherland-Hodgman clipping of a polygon to the box (x_min, x_max, y_min, y_max)."""
    x_min, x_max, y_min, y_max = box
    edges = [(0, x_min, 1.0), (0, x_max, -1.0), (1, y_min, 1.0), (1, y_max, -1.0)]
    polygon = points
    for axis, limit, sign in edges:
        if len(polygon) == 0:
            break
        out = []
        prev = polygon[-1]
        for cur in polygon:
            cur_in = sign * (cur[axis] - limit) >= 0
            prev_in = sign * (prev[axis] - limit) >= 0
            if cur_in != prev_in:
                t = (limit - prev[axis]) / (cur[axis] - prev[axis])
                out.append(prev + t * (cur - prev))
            if cur_in:
                out.append(cur)
            prev = cur
        polygon = np.array(out).reshape(-1, 2)
    return polygon


def _drop_redundant(polygon: np.ndarray) -> np.ndarray:
    """Drop repeated vertices and vertices in the middle of a straight run, such as a box edge."""
    keep = []
    n = len(polygon)
    for i in range(n):
        prev, cur, nxt = polygon[i - 1], polygon[i], polygon[(i + 1) % n]
        if np.allclose(cur, prev):
            continue
        cross = (cur[0] - prev[0]) * (nxt[1] - cur[1]) - (cur[1] - prev[1]) * (nxt[0] - cur[0])
        if abs(cross) < 1e-9:
            continue
        keep.append(cur)
    return np.array(keep).reshape(-1, 2)
