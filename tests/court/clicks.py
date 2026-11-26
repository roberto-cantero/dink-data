"""Synthetic clicks from a synthetic camera, for the solver tests. No real footage.

Each click is the camera's projection of a painted line's centre, as a person would click it,
with optional pixel noise. Points outside the frame are dropped, as a person would skip them.
"""

from collections.abc import Iterable
from typing import Any

import numpy as np

from dinkdata.contracts.camera import CameraCalibration
from dinkdata.contracts.camera_clicks import (
    COURT_LINES,
    FLOOR_KEYPOINTS,
    NET_TOPS,
    CameraClicks,
    CourtLine,
    FloorKeypoint,
    NetTop,
)
from dinkdata.court.floor import court_to_image
from dinkdata.court.keypoints import COURT_LINE_ENDS, KEYPOINTS
from dinkdata.court.solver import line_centre
from tests.court.cameras import CAMERA_ID, HEIGHT, WIDTH

VIDEO = (WIDTH, HEIGHT)
POINTS_PER_LINE = 5


def make_clicks(
    camera: CameraCalibration,
    *,
    noise_px: float = 0.0,
    seed: int = 0,
    keypoints: Iterable[FloorKeypoint] = FLOOR_KEYPOINTS,
    lines: Iterable[CourtLine] = COURT_LINES,
    net_tops: Iterable[NetTop] = NET_TOPS,
    overlay_rects: list[tuple[float, float, float, float]] | None = None,
) -> CameraClicks:
    """The clicks a careful person would make on `camera`, limited to the names given."""
    rng = np.random.default_rng(seed)

    def project(points: np.ndarray) -> np.ndarray:
        pixels = court_to_image(camera, points, video_size=VIDEO)
        return pixels + rng.normal(0.0, noise_px, pixels.shape)

    def inside(pixel: np.ndarray) -> bool:
        x, y = pixel
        return bool(np.isfinite(pixel).all() and 0 <= x <= WIDTH and 0 <= y <= HEIGHT)

    def centre3(name: FloorKeypoint | NetTop) -> list[float]:
        x, y, h = KEYPOINTS[name]
        return [*line_centre((x, y)), h]

    floor_names = list(keypoints)
    kp_pixels = project(np.array([centre3(n) for n in floor_names]))
    net_names = list(net_tops)
    net_pixels = (
        project(np.array([centre3(n) for n in net_names])) if net_names else np.empty((0, 2))
    )

    line_points: dict[str, list[list[float]]] = {}
    for line in lines:
        start, end = (np.array(line_centre(p)) for p in COURT_LINE_ENDS[line])
        steps = np.linspace(0.0, 1.0, 64)[:, None]
        floor = start + steps * (end - start)
        seen = [
            i for i, p in enumerate(court_to_image(camera, floor, video_size=VIDEO)) if inside(p)
        ]
        if len(seen) < 2:
            continue
        # Spread the clicks over the part of the line in view, as the labelling guide asks.
        picks = np.linspace(steps[seen[0], 0], steps[seen[-1], 0], POINTS_PER_LINE)[:, None]
        pixels = [p for p in project(start + picks * (end - start)) if inside(p)]
        if len(pixels) >= 2:
            line_points[line] = [list(map(float, p)) for p in pixels]

    record: dict[str, Any] = {
        "schema": "dinkdata.camera_clicks/v1",
        "camera_id": CAMERA_ID,
        "version": 1,
        "video_id": "v_5eed00000000e001",
        "frames": [0, 100, 200],
        "single_frame": None,
        "image_size": {"width": WIDTH, "height": HEIGHT},
        "keypoints": {
            n: list(map(float, p)) for n, p in zip(floor_names, kp_pixels, strict=True) if inside(p)
        },
        "line_points": line_points,
        "net_tops": {
            n: list(map(float, p)) for n, p in zip(net_names, net_pixels, strict=True) if inside(p)
        },
        "overlay_rects": overlay_rects or [],
        "labeller": "synthetic",
        "saved_at": "2026-11-26T12:00:00Z",
    }
    return CameraClicks.model_validate(record)
