"""`{video_id}.frames.parquet`: every decoded frame's time. Owner: Robby (DESIGN 6.1, ADR 0005).

PickleCam videos drop frames, so this table is the only way to turn a frame into a time. One row
per decoded frame, with `frame` running 0, 1, 2 and so on. `t` follows `common.t_from_pts`.
`dropped_before` counts the frames missing before this one: a gap of about two nominal frame
lengths gives 1. `duplicate` marks a frame whose picture repeats the previous one.
"""

import numpy as np
import pyarrow as pa
from pydantic import Field

from dinkdata.contracts.common import Frame, Seconds, StrictModel
from dinkdata.contracts.game_log import EventLog
from dinkdata.contracts.tables import TableContract, check_frame_order, column

SCHEMA_NAME = "dinkdata.frames/v1"

FRAMES_SCHEMA = pa.schema(
    [
        pa.field("frame", pa.int64(), nullable=False),
        pa.field("t", pa.float64(), nullable=False),
        pa.field("dropped_before", pa.int32(), nullable=False),
        pa.field("duplicate", pa.bool_(), nullable=False),
    ],
    metadata={"schema": SCHEMA_NAME},
)


class FrameRow(StrictModel):
    """One row of frames.parquet."""

    frame: Frame
    t: Seconds
    dropped_before: int = Field(ge=0, le=2**31 - 1, description="Frames missing before this one.")
    duplicate: bool = Field(description="true when the picture repeats the previous frame's.")


def _rules(table: pa.Table) -> list[str]:
    errors = check_frame_order(table)
    frame, t = column(table, "frame"), column(table, "t")
    if frame[0] != 0 or np.any(np.diff(frame) != 1):
        errors.append("frame must run 0, 1, 2, ... with no gaps")
    if t[0] != 0:
        errors.append("the first frame's t must be 0")
    if np.any(column(table, "dropped_before") < 0):
        errors.append("dropped_before must be non-negative")
    elif column(table, "dropped_before")[0] != 0:
        errors.append("the first frame has no dropped frames before it")
    return errors


FRAMES = TableContract(FRAMES_SCHEMA, FrameRow, _rules)


def check_log_frames(log: EventLog, frames: pa.Table, tolerance: float = 1e-3) -> list[str]:
    """Rules between events.json and its frames.parquet: frame counts and every frame's t."""
    t = column(frames, "t")
    errors = []
    dropped = int(column(frames, "dropped_before").sum())
    if log.video.dropped_frames != dropped:
        errors.append(f"video.dropped_frames is {log.video.dropped_frames}, frames has {dropped}")
    for game in log.games:
        for rally in game.rallies:
            marks = [
                (rally.id, rally.start_frame, rally.start_t),
                (rally.id, rally.end_frame, rally.end_t),
            ] + [(e.id, e.frame, e.t) for e in rally.events]
            for name, frame, time in marks:
                if frame >= len(t):
                    errors.append(f"{name}: frame {frame} is past the video's last frame")
                elif abs(t[frame] - time) > tolerance:
                    errors.append(f"{name}: t {time} doesn't match frame {frame}'s t {t[frame]}")
    return errors
