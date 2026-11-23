"""Floor functions: move between raw video pixels and court feet (docs/COURT.md).

Every function takes a `CameraCalibration` (`camera.json` v1) and needs only numpy, so the
core install can run it without scipy or OpenCV.

Court coordinates are right-handed. With x across the court and y toward the camera, the
third axis points down into the floor, so a point `h` ft above the floor has z = -h.
`rotation` and `translation` take these court coordinates to camera coordinates, where the
camera looks along +z, image x runs right and image y runs down. The functions take heights
above the floor and turn them into z themselves.

Pixels are raw, distorted, full-resolution video pixels. Each function checks the video's
size against the calibration's `image_size` and raises on a mismatch, so a 720p copy is never
mapped with 1080p numbers.
"""

import re
from pathlib import Path

import numpy as np

from dinkdata.contracts.camera import CameraCalibration
from dinkdata.court.keypoints import COURT_LINES, CourtLine

CAMERAS = Path("data/cameras")
"""Local calibrations, laid out as in R2. docs/DATA.md has the rclone command that fills it."""

VideoSize = tuple[int, int]
"""(width, height) of the video the pixels come from."""


def load_camera(
    camera_id: str, version: int | None = None, *, root: Path = CAMERAS
) -> CameraCalibration:
    """Read and validate `{root}/{camera_id}/v{n}/camera.json`. Never reads R2.

    With no `version`, it reads the highest version on disk. Raises `FileNotFoundError` when
    the file isn't there, a pydantic `ValidationError` when it breaks the contract, and
    `ValueError` when its camera id or version differs from its folder.
    """
    folder = root / camera_id
    if version is None:
        versions = [
            int(m.group(1))
            for p in folder.glob("v*/camera.json")
            if (m := re.fullmatch(r"v([1-9][0-9]*)", p.parent.name))
        ]
        if not versions:
            raise FileNotFoundError(
                f"no calibration of {camera_id} in {root}. Copy them from R2 with "
                f"`uv run --env-file .env rclone copy r2:dinkdata/cameras {root} --immutable`"
            )
        version = max(versions)
    path = folder / f"v{version}" / "camera.json"
    if not path.is_file():
        raise FileNotFoundError(f"no calibration {camera_id} v{version} at {path}")
    camera = CameraCalibration.model_validate_json(path.read_text())
    if (camera.camera_id, camera.version) != (camera_id, version):
        raise ValueError(
            f"{path} holds {camera.camera_id} v{camera.version}, not {camera_id} v{version}"
        )
    return camera


def court_to_image(
    camera: CameraCalibration, points: np.ndarray, *, video_size: VideoSize
) -> np.ndarray:
    """Project court points to raw video pixels.

    `points` is (N, 2) floor points or (N, 3) points with a height above the floor, in feet.
    Returns (N, 2) pixels. A row is NaN when the point is behind the camera or beyond the
    edge of the lens model, where the distortion folds back.
    """
    _check_size(camera, video_size)
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] not in (2, 3):
        raise ValueError(f"points must be (N, 2) or (N, 3), not {points.shape}")
    court = np.zeros((len(points), 3))
    court[:, :2] = points[:, :2]
    if points.shape[1] == 3:
        court[:, 2] = -points[:, 2]
    cam = court @ _rotation(camera).T + np.asarray(camera.translation)
    with np.errstate(divide="ignore", invalid="ignore"):
        ideal = cam[:, :2] / cam[:, 2:3]
    ideal[cam[:, 2] <= 0] = np.nan
    return _to_pixels(camera, _distort(camera, ideal))


def image_to_court(
    camera: CameraCalibration, pixels: np.ndarray, *, video_size: VideoSize
) -> np.ndarray:
    """Map raw video pixels to floor points in court feet.

    `pixels` is (N, 2). Returns (N, 2) court feet. A row is NaN for a pixel at or above the
    horizon, or beyond the edge of the lens model. Only points on the floor, such as feet
    and bounces, map to the right place (docs/COURT.md).
    """
    _check_size(camera, video_size)
    pixels = np.asarray(pixels, dtype=float)
    if pixels.ndim != 2 or pixels.shape[1] != 2:
        raise ValueError(f"pixels must be (N, 2), not {pixels.shape}")
    ideal = _undistort(camera, _from_pixels(camera, pixels))
    rot = _rotation(camera)
    rays = np.column_stack([ideal, np.ones(len(ideal))]) @ rot  # R^T @ ray, per row
    centre = -rot.T @ np.asarray(camera.translation)
    with np.errstate(divide="ignore", invalid="ignore"):
        scale = -centre[2] / rays[:, 2]
        court = centre[:2] + scale[:, None] * rays[:, :2]
    court[~(scale > 0) | ~np.isfinite(scale)] = np.nan
    return court


def feet_per_pixel(
    camera: CameraCalibration, points: np.ndarray, *, video_size: VideoSize
) -> np.ndarray:
    """The floor distance of one pixel at each court point, in feet.

    `points` is (N, 2) floor points. The value is the largest stretch of the local Jacobian
    of `image_to_court`: the floor distance one pixel covers in the direction where it covers
    the most. Multiply a pixel error by it to get a distance on the floor. Returns (N,). A
    value is NaN for a point behind the camera or past the lens fold. A point outside the
    frame but in front of the camera still gets a value.

    The Jacobian is the inverse of `court_to_image`'s, which has a closed form.
    """
    _check_size(camera, video_size)
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError(f"points must be (N, 2), not {points.shape}")
    rot = _rotation(camera)
    cam = points @ rot[:, :2].T + np.asarray(camera.translation)
    d_cam = rot[:, :2]  # d(camera coords) / d(x, y), the same for every floor point
    k1, k2 = camera.distortion.k1, camera.distortion.k2
    focal = np.diag([camera.intrinsics.fx, camera.intrinsics.fy])
    r2_max = _max_radius(camera) ** 2
    values = np.full(len(points), np.nan)
    for n, (X, Y, Z) in enumerate(cam):
        if Z <= 0:
            continue
        xn, yn = X / Z, Y / Z
        r2 = xn * xn + yn * yn
        if r2 > r2_max:
            continue
        d_ideal = (d_cam[:2] - np.outer([xn, yn], d_cam[2])) / Z  # 2x2
        d_r2 = 2 * (xn * d_ideal[0] + yn * d_ideal[1])
        d_scale = (k1 + 2 * k2 * r2) * d_r2
        d_distorted = _radial(camera, r2) * d_ideal + np.outer([xn, yn], d_scale)
        forward = focal @ d_distorted
        values[n] = np.linalg.norm(np.linalg.inv(forward), 2)
    return values


LINE_SAMPLES = 64
"""Points per court line in `court_lines_image`, enough to show the lens bend smoothly."""


def court_lines_image(
    camera: CameraCalibration, *, video_size: VideoSize
) -> dict[CourtLine, np.ndarray]:
    """Each named court line as a polyline of raw video pixels, with the lens bend included.

    Each line is sampled at `LINE_SAMPLES` evenly spaced floor points from its first end to
    its second, so a polyline is (LINE_SAMPLES, 2). A sample the camera can't see is a NaN row.
    The lines are the court's boundaries from docs/COURT.md, not the painted lines' centres.
    """
    steps = np.linspace(0.0, 1.0, LINE_SAMPLES)[:, None]
    lines: dict[CourtLine, np.ndarray] = {}
    for name, (start, end) in COURT_LINES.items():
        floor = np.asarray(start) + steps * (np.asarray(end) - np.asarray(start))
        lines[name] = court_to_image(camera, floor, video_size=video_size)
    return lines


def _check_size(camera: CameraCalibration, video_size: VideoSize) -> None:
    size = camera.image_size
    if tuple(video_size) != (size.width, size.height):
        raise ValueError(
            f"the video is {video_size[0]}x{video_size[1]} but camera {camera.camera_id} "
            f"v{camera.version} was calibrated at {size.width}x{size.height}"
        )


def _rotation(camera: CameraCalibration) -> np.ndarray:
    """Rodrigues vector to rotation matrix."""
    vec = np.asarray(camera.rotation, dtype=float)
    angle = float(np.linalg.norm(vec))
    if angle == 0:
        return np.eye(3)
    kx, ky, kz = vec / angle
    k = np.array([[0, -kz, ky], [kz, 0, -kx], [-ky, kx, 0]])
    return np.eye(3) + np.sin(angle) * k + (1 - np.cos(angle)) * (k @ k)


def _max_radius(camera: CameraCalibration) -> float:
    """The undistorted radius where the radial mapping stops growing, or inf if it never does.

    The distorted radius is r (1 + k1 r^2 + k2 r^4). Its derivative 1 + 3 k1 u + 5 k2 u^2,
    with u = r^2, first reaches zero at the smallest positive root.
    """
    k1, k2 = camera.distortion.k1, camera.distortion.k2
    roots = np.roots([5 * k2, 3 * k1, 1]) if k2 != 0 else np.roots([3 * k1, 1])
    positive = [r.real for r in roots if abs(r.imag) < 1e-12 and r.real > 0]
    return float(np.sqrt(min(positive))) if positive else np.inf


def _radial(camera: CameraCalibration, r2: np.ndarray | float) -> np.ndarray | float:
    """The radial distortion factor 1 + k1 r^2 + k2 r^4, from the squared radius."""
    k1, k2 = camera.distortion.k1, camera.distortion.k2
    return 1 + k1 * r2 + k2 * r2 * r2


def _distort(camera: CameraCalibration, ideal: np.ndarray) -> np.ndarray:
    """Normalised pinhole coordinates to normalised distorted ones. NaN past the lens fold."""
    r2 = (ideal**2).sum(axis=1, keepdims=True)
    distorted = ideal * _radial(camera, r2)
    distorted[(r2 > _max_radius(camera) ** 2)[:, 0]] = np.nan
    return distorted


NEWTON_STEPS = 50
"""Most Newton steps for undistortion. A row that hasn't converged by then is NaN."""
NEWTON_TOLERANCE = 1e-12
"""Largest radius error, in focal lengths, that counts as converged. About 1e-9 px."""


def _undistort(camera: CameraCalibration, distorted: np.ndarray) -> np.ndarray:
    """Invert the radial distortion with Newton iteration on the radius.

    Solves r (1 + k1 r^2 + k2 r^4) = rd for each distorted radius rd, starting at r = rd and
    staying inside the radius where the mapping folds. A radius past the fold is NaN.
    """
    k1, k2 = camera.distortion.k1, camera.distortion.k2
    if k1 == 0 and k2 == 0:
        return distorted.copy()
    r_max = _max_radius(camera)
    rd = np.sqrt((distorted**2).sum(axis=1))
    rd_max = r_max * _radial(camera, r_max**2) if np.isfinite(r_max) else np.inf
    r = np.minimum(rd, r_max)
    with np.errstate(divide="ignore", invalid="ignore"):
        for _ in range(NEWTON_STEPS):
            r2 = r * r
            slope = 1 + 3 * k1 * r2 + 5 * k2 * r2 * r2
            r = np.clip(r - (r * _radial(camera, r2) - rd) / slope, 0, r_max)
        converged = np.abs(r * _radial(camera, r * r) - rd) <= NEWTON_TOLERANCE
        scale = np.where(rd > 0, r / rd, 1.0)
    ideal = distorted * scale[:, None]
    ideal[(rd > rd_max) | ~converged] = np.nan
    return ideal


def _to_pixels(camera: CameraCalibration, distorted: np.ndarray) -> np.ndarray:
    i = camera.intrinsics
    return distorted * np.array([i.fx, i.fy]) + np.array([i.cx, i.cy])


def _from_pixels(camera: CameraCalibration, pixels: np.ndarray) -> np.ndarray:
    i = camera.intrinsics
    return (pixels - np.array([i.cx, i.cy])) / np.array([i.fx, i.fy])
