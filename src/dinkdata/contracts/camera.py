"""`camera.json`: one calibration of one camera. Owner: Robby (docs/COURT.md, DESIGN 6.3).

A pinhole camera with radial distortion (k1, k2). `rotation` is a Rodrigues vector and
`translation` is in feet. Together they take court coordinates to camera coordinates. Saved
as `cameras/{camera_id}/v{n}/camera.json`. A new calibration is a new version.
"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from dinkdata.contracts.common import CameraId, CameraSetup, StrictModel
from dinkdata.contracts.game_log import EventLog

Finite = Annotated[float, Field(allow_inf_nan=False)]
Point = tuple[Finite, Finite]
Polygon = Annotated[list[Point], Field(min_length=3)]


class ImageSize(StrictModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class Intrinsics(StrictModel):
    fx: float = Field(gt=0, allow_inf_nan=False, description="Focal length in pixels.")
    fy: float = Field(gt=0, allow_inf_nan=False, description="Focal length in pixels.")
    cx: float = Field(allow_inf_nan=False, description="Principal point in pixels.")
    cy: float = Field(allow_inf_nan=False, description="Principal point in pixels.")


class Distortion(StrictModel):
    k1: Finite
    k2: Finite


class CameraCalibration(StrictModel):
    """One calibration. Rules JSON Schema can't express are checked in code."""

    schema_: Literal["dinkdata.camera/v1"] = Field(alias="schema")
    camera_id: CameraId
    version: int = Field(ge=1)
    model: str | None = Field(max_length=80, description="Camera model. null when unknown.")
    setup: CameraSetup
    image_size: ImageSize
    intrinsics: Intrinsics
    distortion: Distortion
    rotation: tuple[Finite, Finite, Finite] = Field(
        description="Rodrigues vector, court to camera."
    )
    translation: tuple[Finite, Finite, Finite] = Field(description="Feet, court to camera.")
    reprojection_error_px: float = Field(
        ge=0, allow_inf_nan=False, description="Mean error on held-back clicks, in pixels."
    )
    visible_region: Polygon = Field(
        description="The floor the camera sees, in court feet, clipped at the horizon."
    )
    overlay_masks: list[Polygon] = Field(
        description="Image regions to ignore, such as the watermark and logo, in pixels."
    )
    source: Literal["clicks", "auto"] = Field(description="Hand clicks, or automatic (M4).")

    @model_validator(mode="after")
    def _inside_image(self) -> "CameraCalibration":
        w, h = self.image_size.width, self.image_size.height
        if not (0 <= self.intrinsics.cx <= w and 0 <= self.intrinsics.cy <= h):
            raise ValueError("the principal point must be inside the image")
        for mask in self.overlay_masks:
            if any(not (0 <= x <= w and 0 <= y <= h) for x, y in mask):
                raise ValueError("overlay masks must be inside the image")
        return self


def check_log_camera(log: EventLog, camera: CameraCalibration) -> list[str]:
    """events.json names the calibration it was made with."""
    if (log.camera.id, log.camera.version) != (camera.camera_id, camera.version):
        return [
            f"events.json uses {log.camera.id} v{log.camera.version}, "
            f"not {camera.camera_id} v{camera.version}"
        ]
    return []
