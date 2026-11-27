"""Calibrate mode: clicks on a camera's picture in, a versioned calibration out (DESIGN 6.3).

The page shows the per-pixel median of about 25 frames spread across one of the camera's
videos, which removes the players, or a single frame when the median blurs a line. A person
clicks the named keypoints and net tops in full-resolution video pixels. This module turns
those clicks into a `camera_clicks/v1` record, fits it with `dinkdata.court.solver`, and
gives the page what it draws: the fitted court's line centres, each keypoint's held-back
error and the 3 worst keypoints.

Saves go through `save`: R2 first with `dinkdata.data.r2.put_new_version`, so a version is
never replaced and a refused number moves on to the next, then the same files to the local
`data/cameras/{camera_id}/v{n}/`. With R2 off, the save numbers after the local versions only.
"""

import datetime as dt
import re
from collections.abc import Sequence
from pathlib import Path
from typing import get_args

import numpy as np
import pyarrow as pa
from pydantic import Field

from dinkdata.contracts.camera import CameraCalibration
from dinkdata.contracts.camera_clicks import (
    FLOOR_KEYPOINTS,
    NET_TOPS,
    CameraClicks,
    CourtLine,
    FloorKeypoint,
    LinePoints,
    NetTop,
    Pixel,
    Rect,
)
from dinkdata.contracts.catalog import CatalogRow
from dinkdata.contracts.common import CameraSetup, Frame, StrictModel, to_json
from dinkdata.court.floor import court_to_image
from dinkdata.court.keypoints import COURT_LINE_ENDS, KEYPOINTS, NET_HEIGHT_CENTRE, KeypointName
from dinkdata.court.solver import CalibrationFit, line_centre, solve
from dinkdata.court.zones import CENTRE_X, NET_Y, WIDTH
from dinkdata.data import r2

SAMPLES = 25
"""Frames in the median picture, spread evenly across the video."""
WORST = 3
"""The keypoints with the largest held-back error that the page lists."""
LINE_SAMPLES = 64
"""Points per fitted court line in the overlay, enough to show the lens bend."""
NET_SAMPLES = 33
"""Points along the fitted net top in the overlay."""
CAMERAS = "cameras"
"""The R2 folder of calibrations, laid out as the local `data/cameras/`."""

_VERSION = re.compile(r"v([1-9][0-9]*)")


class Clicks(StrictModel):
    """What the page sends to fit or save. Pixels are full-resolution video pixels."""

    keypoints: dict[FloorKeypoint, Pixel] = Field(default_factory=dict)
    net_tops: dict[NetTop, Pixel] = Field(default_factory=dict)
    line_points: dict[CourtLine, LinePoints] = Field(default_factory=dict)
    overlay_rects: list[Rect] = Field(default_factory=list)
    single_frame: Frame | None = None
    setup: CameraSetup | None = Field(
        default=None, description="The camera setup the person picked. Fit and save need it."
    )


class NoSetup(ValueError):
    """The page asked to fit or save before the person picked a camera setup."""


def sample_frames(count: int, samples: int = SAMPLES) -> list[int]:
    """`samples` frame indexes spread evenly from the first frame to the last, or every frame
    of a shorter video."""
    if count <= 0:
        raise ValueError("the video has no frames")
    return sorted({round(i) for i in np.linspace(0, count - 1, min(samples, count))})


def median_picture(video: Path, frames: pa.Table, indexes: Sequence[int]) -> np.ndarray:
    """The per-pixel median of the frames at `indexes`, as height x width x 3 RGB uint8.

    With an even count it takes the lower of the two middle values, so it stays uint8 and
    never needs a float copy of every frame.
    """
    from dinkdata.video.reader import VideoReader  # needs the cv extra

    with VideoReader(video, frames) as reader:
        stack = np.stack([reader[i].image for i in indexes])
    middle = (len(stack) - 1) // 2
    return np.partition(stack, middle, axis=0)[middle]


SETUPS: tuple[CameraSetup, ...] = get_args(CameraSetup)


def diagram() -> dict[str, object]:
    """The court diagram the page draws: each point to click, in order, and each court line,
    in court feet. The floor keypoints come first, then the three net tops."""
    return {
        "points": [
            {"name": name, "court": list(KEYPOINTS[name][:2]), "net": name in NET_TOPS}
            for name in (*FLOOR_KEYPOINTS, *NET_TOPS)
        ],
        "lines": {name: [list(a), list(b)] for name, (a, b) in COURT_LINE_ENDS.items()},
        "setups": list(SETUPS),
    }


def to_clicks(
    clicks: Clicks,
    *,
    camera_id: str,
    video_id: str,
    version: int,
    frames: list[int],
    image_size: tuple[int, int],
    labeller: str,
    saved_at: dt.datetime | None = None,
) -> CameraClicks:
    """The `camera_clicks/v1` record for the page's clicks. Raises a pydantic
    `ValidationError` when a click is outside the image."""
    width, height = image_size
    return CameraClicks.model_validate(
        {
            "schema": "dinkdata.camera_clicks/v1",
            "camera_id": camera_id,
            "version": version,
            "video_id": video_id,
            "frames": frames,
            "single_frame": clicks.single_frame,
            "image_size": {"width": width, "height": height},
            "keypoints": clicks.keypoints,
            "line_points": clicks.line_points,
            "net_tops": clicks.net_tops,
            "overlay_rects": clicks.overlay_rects,
            "labeller": labeller,
            "saved_at": saved_at or dt.datetime.now(dt.UTC),
        }
    )


def fit(record: CameraClicks, setup: CameraSetup | None) -> CalibrationFit:
    """Fit the clicks, or raise `NoSetup` or the solver's `CalibrationError`."""
    if setup is None:
        raise NoSetup("Pick the camera setup before you fit or save.")
    return solve(record, setup=setup)


def view(result: CalibrationFit) -> dict[str, object]:
    """What the page shows for a fit: errors, the 3 worst keypoints and the fitted court."""
    camera = result.camera
    size = (camera.image_size.width, camera.image_size.height)
    held_back = result.held_back_px
    worst = sorted(held_back, key=lambda name: held_back[name], reverse=True)[:WORST]

    names: list[KeypointName] = [*FLOOR_KEYPOINTS, *NET_TOPS]
    centres = [[*line_centre(KEYPOINTS[n][:2]), KEYPOINTS[n][2]] for n in names]
    fitted = court_to_image(camera, np.array(centres), video_size=size)
    return {
        "error_px": camera.reprojection_error_px,
        "held_back_px": held_back,
        "worst": worst,
        "warnings": result.warnings,
        "lines": {name: _polyline(points) for name, points in overlay_lines(result).items()},
        "net": _polyline(_net_top(result)),
        "fitted": dict(zip(names, _polyline(fitted), strict=True)),
    }


def overlay_lines(result: CalibrationFit) -> dict[CourtLine, np.ndarray]:
    """Each court line's painted centre in raw video pixels, (LINE_SAMPLES, 2) with NaN rows
    where the camera can't see it.

    People click the centre of a painted line, so the overlay draws centres, 1 in inside
    docs/COURT.md's boundaries. Drawing boundaries would make a good fit look about 3 px off
    near a low camera.
    """
    camera = result.camera
    size = (camera.image_size.width, camera.image_size.height)
    steps = np.linspace(0.0, 1.0, LINE_SAMPLES)[:, None]
    lines: dict[CourtLine, np.ndarray] = {}
    for name, (start, end) in COURT_LINE_ENDS.items():
        a, b = np.array(line_centre(start)), np.array(line_centre(end))
        lines[name] = court_to_image(camera, a + steps * (b - a), video_size=size)
    return lines


def _net_top(result: CalibrationFit) -> np.ndarray:
    """The top of the net at its rule-book heights, sideline to sideline."""
    camera = result.camera
    x = np.linspace(0.0, WIDTH, NET_SAMPLES)
    sideline = KEYPOINTS["net_top_left"][2]
    height = sideline + (NET_HEIGHT_CENTRE - sideline) * (1 - np.abs(x - CENTRE_X) / CENTRE_X)
    points = np.column_stack([x, np.full_like(x, NET_Y), height])
    return court_to_image(
        camera, points, video_size=(camera.image_size.width, camera.image_size.height)
    )


def _polyline(points: np.ndarray) -> list[list[float] | None]:
    """Pixels as JSON, with None where a point isn't visible."""
    return [[float(x), float(y)] if np.isfinite(x) and np.isfinite(y) else None for x, y in points]


# ---- saving ----


def local_versions(folder: Path) -> list[int]:
    """The `v<n>/` folders in a camera's local folder, oldest first."""
    if not folder.is_dir():
        return []
    found = [int(m.group(1)) for p in folder.iterdir() if (m := _VERSION.fullmatch(p.name))]
    return sorted(found)


def save(
    record: CameraClicks,
    result: CalibrationFit,
    *,
    cameras: Path,
    store: r2.ListingStore | None,
) -> int:
    """Save `camera.json` and `clicks.json` as the camera's next version and return it.

    With a store, the version is claimed in R2 first, after any version in R2 or on this
    Mac, and a refused number moves on to the next. Then the same files go to
    `cameras/{camera_id}/v{n}/` locally, so the local folder never holds a version R2 refused.
    Raises `r2.RcloneError` when R2 fails, and then writes nothing locally.
    """
    camera_id = record.camera_id
    folder = cameras / camera_id

    def files(n: int) -> dict[str, bytes]:
        clicks = CameraClicks.model_validate({**record.model_dump(by_alias=True), "version": n})
        camera = CameraCalibration.model_validate(
            {**result.camera.model_dump(by_alias=True), "version": n}
        )
        return {
            f"v{n}/clicks.json": to_json(clicks).encode(),
            f"v{n}/camera.json": to_json(camera).encode(),
        }

    after = max([0, *local_versions(folder)])
    if store is not None:
        n = r2.put_new_version(store, f"{CAMERAS}/{camera_id}", files, after=after)
        _write_local(folder, n, files(n))
        return n
    n = after + 1
    while True:
        try:
            _write_local(folder, n, files(n))
        except FileExistsError:
            n += 1
            continue
        return n


def _write_local(folder: Path, n: int, files: dict[str, bytes]) -> None:
    """Write one version's files into a new `v<n>/` folder. Raises if the folder exists."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"v{n}").mkdir()
    for name, data in files.items():
        (folder / name).write_bytes(data)


# ---- picking the video ----


def pick_video(rows: Sequence[CatalogRow], camera_id: str, video_id: str | None = None) -> str:
    """The camera's first video in the catalog, or `video_id` after checking it is the
    camera's. Raises `ValueError` with what to do."""
    videos = [row.video_id for row in rows if row.camera_id == camera_id]
    if not videos:
        raise ValueError(
            f"the catalog has no video of camera {camera_id}. Ingest one with `dink ingest`."
        )
    if video_id is None:
        return videos[0]
    if video_id not in videos:
        raise ValueError(
            f"{video_id} isn't a video of camera {camera_id} in the catalog. Its videos are "
            f"{', '.join(videos)}."
        )
    return video_id
