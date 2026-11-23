"""`clicks.json`: the raw clicks one calibration was fitted from. Owner: Robby (ADR 0020).

Saved as `cameras/{camera_id}/v{n}/clicks.json`, beside the `camera.json` fitted from it, so
a camera can be refitted without new clicks. Pixels are full-resolution video pixels with
sub-pixel precision, origin at the top-left corner of the image. A skipped point or court line
is absent.

The keypoint, net top and court line names are the ones in `docs/COURT.md`. This module is
their one definition: code imports them from here and never numbers them.
"""

from typing import Annotated, Literal, get_args

from pydantic import AwareDatetime, Field, field_validator, model_validator

from dinkdata.contracts.camera import Finite, ImageSize
from dinkdata.contracts.common import CameraId, Frame, Handle, StrictModel, VideoId

FloorKeypoint = Literal[
    "far_left_corner",
    "far_right_corner",
    "near_right_corner",
    "near_left_corner",
    "far_kitchen_left",
    "far_kitchen_right",
    "near_kitchen_right",
    "near_kitchen_left",
    "far_kitchen_centre",
    "near_kitchen_centre",
    "far_baseline_centre",
    "near_baseline_centre",
]
"""The named keypoints on the floor (docs/COURT.md)."""

NetTop = Literal["net_top_left", "net_top_centre", "net_top_right"]
"""Where the top of the net crosses above each sideline and the centre line."""

CourtLine = Literal[
    "far_baseline",
    "near_baseline",
    "left_sideline",
    "right_sideline",
    "far_kitchen_line",
    "near_kitchen_line",
    "far_centre_line",
    "near_centre_line",
]
"""The named painted lines. The net's floor line is left out, because the net hides it."""

FLOOR_KEYPOINTS: tuple[FloorKeypoint, ...] = get_args(FloorKeypoint)
NET_TOPS: tuple[NetTop, ...] = get_args(NetTop)
COURT_LINES: tuple[CourtLine, ...] = get_args(CourtLine)

MIN_LINE_POINTS = 2
MAX_LINE_POINTS = 5

Pixel = tuple[Finite, Finite]
LinePoints = Annotated[
    list[Pixel],
    Field(
        min_length=MIN_LINE_POINTS,
        max_length=MAX_LINE_POINTS,
        description="Points clicked along one court line. The tool asks for 3 to 5.",
    ),
]
Rect = Annotated[
    tuple[Finite, Finite, Finite, Finite],
    Field(description="x_min, y_min, x_max, y_max in pixels."),
]


class CameraClicks(StrictModel):
    """The clicks behind one calibration. Rules JSON Schema can't express are checked in code."""

    schema_: Literal["dinkdata.camera_clicks/v1"] = Field(alias="schema")
    camera_id: CameraId
    version: int = Field(ge=1, description="The camera.json version fitted from these clicks.")
    video_id: VideoId = Field(description="The video the picture was taken from.")
    frames: list[Frame] = Field(
        min_length=1,
        description="Frames behind the picture: about 25 for the median, or 1 for a single frame.",
    )
    image_size: ImageSize
    keypoints: dict[FloorKeypoint, Pixel] = Field(description="Floor keypoint clicks by name.")
    line_points: dict[CourtLine, LinePoints] = Field(description="Line points by court line.")
    net_tops: dict[NetTop, Pixel] = Field(description="Net top clicks by name.")
    overlay_rects: list[Rect] = Field(
        description="Rectangles over the watermark, logo and other overlays."
    )
    labeller: Handle
    saved_at: AwareDatetime

    @field_validator("frames")
    @classmethod
    def _frames_increase(cls, frames: list[int]) -> list[int]:
        if any(b <= a for a, b in zip(frames, frames[1:], strict=False)):
            raise ValueError("frames must be in increasing order with no repeats")
        return frames

    @model_validator(mode="after")
    def _inside_image(self) -> "CameraClicks":
        w, h = self.image_size.width, self.image_size.height

        def inside(x: float, y: float) -> bool:
            return 0 <= x <= w and 0 <= y <= h

        for name, (x, y) in {**self.keypoints, **self.net_tops}.items():
            if not inside(x, y):
                raise ValueError(f"{name} at ({x}, {y}) is outside the {w}x{h} image")
        for line, points in self.line_points.items():
            if any(not inside(x, y) for x, y in points):
                raise ValueError(f"a point on {line} is outside the {w}x{h} image")
        for x0, y0, x1, y1 in self.overlay_rects:
            if not (x1 > x0 and y1 > y0):
                raise ValueError("an overlay rectangle needs x_max > x_min and y_max > y_min")
            if not (inside(x0, y0) and inside(x1, y1)):
                raise ValueError(f"an overlay rectangle is outside the {w}x{h} image")
        return self
