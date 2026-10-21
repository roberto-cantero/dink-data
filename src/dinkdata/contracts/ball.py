"""`ball.parquet` and `ball_labels.parquet`: the ball in image pixels. Owner: Robby (DESIGN 6.4).

`ball.parquet` is the tracker's output: one row per frame it ran on, sorted by frame. `x` and
`y` are the ball's centre in pixels and are null when the ball isn't visible. `interpolated`
marks a short gap filled between detections. `peaks` holds up to 3 candidate positions from the
heatmap as (x, y, score), best first, so later stages can recover from a wrong pick.

`ball_labels.parquet` is ball clicks from CVAT, converted. `clicked` is false for frames CVAT
interpolated between two clicks. Every row carries the video's split, so a table never mixes
training and test labels.
"""

import numpy as np
import pyarrow as pa
from pydantic import Field, model_validator

from dinkdata.contracts.common import Conf, Frame, Seconds, Split, StrictModel
from dinkdata.contracts.tables import (
    TableContract,
    check_frame_order,
    check_position,
    check_unit,
    column,
    fixed_list,
)

BALL_SCHEMA_NAME = "dinkdata.ball/v1"
LABELS_SCHEMA_NAME = "dinkdata.ball_labels/v1"
MAX_PEAKS = 3
SPLITS = ("train", "dev", "test")

BALL_SCHEMA = pa.schema(
    [
        pa.field("frame", pa.int64(), nullable=False),
        pa.field("t", pa.float64(), nullable=False),
        pa.field("x", pa.float32()),
        pa.field("y", pa.float32()),
        pa.field("visible", pa.bool_(), nullable=False),
        pa.field("conf", pa.float32(), nullable=False),
        pa.field("interpolated", pa.bool_(), nullable=False),
        pa.field("peaks", pa.list_(pa.field("element", fixed_list(pa.float32(), 3))), False),
    ],
    metadata={"schema": BALL_SCHEMA_NAME},
)

BALL_LABELS_SCHEMA = pa.schema(
    [
        pa.field("frame", pa.int64(), nullable=False),
        pa.field("t", pa.float64(), nullable=False),
        pa.field("x", pa.float32()),
        pa.field("y", pa.float32()),
        pa.field("visible", pa.bool_(), nullable=False),
        pa.field("clicked", pa.bool_(), nullable=False),
        pa.field("split", pa.string(), nullable=False),
    ],
    metadata={"schema": LABELS_SCHEMA_NAME},
)

Pixels = float
Peak = tuple[Pixels, Pixels, Conf]


def _check_xy(visible: bool, x: float | None, y: float | None) -> None:
    if (x is None) != (y is None):
        raise ValueError("x and y must both be set or both null")
    if (x is not None) != visible:
        raise ValueError("x and y are set exactly when visible is true")


class BallRow(StrictModel):
    """One row of ball.parquet."""

    frame: Frame
    t: Seconds
    x: float | None = Field(allow_inf_nan=False, description="Pixels. null when not visible.")
    y: float | None = Field(allow_inf_nan=False, description="Pixels. null when not visible.")
    visible: bool
    conf: Conf = Field(description="Confidence that the ball is where x, y say, or absent.")
    interpolated: bool = Field(description="true for a gap filled between detections.")
    peaks: list[Peak] = Field(max_length=MAX_PEAKS, description="(x, y, score), best first.")

    @model_validator(mode="after")
    def _row_rules(self) -> "BallRow":
        _check_xy(self.visible, self.x, self.y)
        if self.interpolated and not self.visible:
            raise ValueError("an interpolated frame has a position, so it is visible")
        return self


class BallLabelRow(StrictModel):
    """One row of ball_labels.parquet."""

    frame: Frame
    t: Seconds
    x: float | None = Field(allow_inf_nan=False, description="Pixels. null when not visible.")
    y: float | None = Field(allow_inf_nan=False, description="Pixels. null when not visible.")
    visible: bool
    clicked: bool = Field(description="false for a frame CVAT interpolated between clicks.")
    split: Split

    @model_validator(mode="after")
    def _row_rules(self) -> "BallLabelRow":
        _check_xy(self.visible, self.x, self.y)
        return self


def _ball_rules(table: pa.Table) -> list[str]:
    errors = check_frame_order(table) + check_position(table) + check_unit(table, "conf")
    if np.any(column(table, "interpolated") & ~column(table, "visible")):
        errors.append("an interpolated frame has a position, so it is visible")
    peaks = table.column("peaks").combine_chunks()
    if np.any(peaks.value_lengths().to_numpy(zero_copy_only=False) > MAX_PEAKS):
        errors.append(f"at most {MAX_PEAKS} peaks per frame")
    scores = peaks.flatten().flatten().to_numpy(zero_copy_only=False)[2::3]
    if np.any(~((scores >= 0) & (scores <= 1))):
        errors.append("peak scores must be between 0 and 1")
    return errors


def _label_rules(table: pa.Table) -> list[str]:
    errors = check_frame_order(table) + check_position(table)
    splits = set(table.column("split").to_pylist())
    if len(splits) != 1 or not splits <= set(SPLITS):
        errors.append(f"split must be one of {', '.join(SPLITS)}, the same on every row")
    return errors


BALL = TableContract(BALL_SCHEMA, BallRow, _ball_rules)
BALL_LABELS = TableContract(BALL_LABELS_SCHEMA, BallLabelRow, _label_rules)
