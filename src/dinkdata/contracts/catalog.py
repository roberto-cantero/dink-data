"""`catalog.parquet`: the list of known videos. Owner: Robby (DESIGN 6.1, docs/DATA.md).

In M0 to M3, `dink ingest` adds a row for each game downloaded by hand. `dink catalog sync`
fills it from PickleCam's endpoint in M4. The table holds opaque ids only. The map back to
PickleCam's ids is `catalog/id_map.parquet`, which is private and has no contract here.
Every game of a facility shares one split, because test sets are whole held-out facilities.
"""

import re

import numpy as np
import pyarrow as pa
from pydantic import AwareDatetime, Field

from dinkdata.contracts.common import (
    CAMERA_ID_PATTERN,
    FACILITY_ID_PATTERN,
    VIDEO_ID_PATTERN,
    CameraId,
    CameraSetup,
    FacilityId,
    Split,
    StrictModel,
    VideoId,
)
from dinkdata.contracts.tables import TableContract, column

SCHEMA_NAME = "dinkdata.catalog/v1"
SETUPS = ("dtl_low", "dtl_high", "diagonal")
SPLITS = ("train", "dev", "test")

CATALOG_SCHEMA = pa.schema(
    [
        pa.field("video_id", pa.string(), nullable=False),
        pa.field("facility_id", pa.string(), nullable=False),
        pa.field("camera_id", pa.string(), nullable=False),
        pa.field("uploaded_at", pa.timestamp("us", tz="UTC")),
        pa.field("duration_s", pa.float64(), nullable=False),
        pa.field("fps_nominal", pa.float64(), nullable=False),
        pa.field("size_bytes", pa.int64(), nullable=False),
        pa.field("setup", pa.string()),
        pa.field("split", pa.string(), nullable=False),
        pa.field("fetched", pa.bool_(), nullable=False),
        pa.field("notes", pa.string()),
    ],
    metadata={"schema": SCHEMA_NAME},
)


class CatalogRow(StrictModel):
    """One row of catalog.parquet: one video."""

    video_id: VideoId
    facility_id: FacilityId
    camera_id: CameraId
    uploaded_at: AwareDatetime | None = Field(description="null when unknown for a hand download.")
    duration_s: float = Field(gt=0, allow_inf_nan=False)
    fps_nominal: float = Field(gt=0, allow_inf_nan=False, description="Never use it for time.")
    size_bytes: int = Field(gt=0)
    setup: CameraSetup | None = Field(description="null until the camera is calibrated.")
    split: Split
    fetched: bool = Field(description="true once the video and its frames.parquet are in R2.")
    notes: str | None = Field(max_length=500, description="Free text. No names or emails.")


def _rules(table: pa.Table) -> list[str]:
    errors = []
    for name, pattern in [
        ("video_id", VIDEO_ID_PATTERN),
        ("facility_id", FACILITY_ID_PATTERN),
        ("camera_id", CAMERA_ID_PATTERN),
    ]:
        if not all(re.fullmatch(pattern, v) for v in table.column(name).to_pylist()):
            errors.append(f"{name} must match {pattern}")
    videos = table.column("video_id").to_pylist()
    if len(set(videos)) != len(videos):
        errors.append("video_id must be unique")
    for name in ("duration_s", "fps_nominal", "size_bytes"):
        values = column(table, name)
        if np.any(~(values > 0)) or not np.all(np.isfinite(values)):
            errors.append(f"{name} must be positive")
    for name, allowed in [("setup", SETUPS), ("split", SPLITS)]:
        values = set(table.column(name).drop_null().to_pylist())
        if not values <= set(allowed):
            errors.append(f"{name} must be one of {', '.join(allowed)}: {sorted(values)}")
    splits: dict[str, set[str]] = {}
    facilities = table.column("facility_id").to_pylist()
    for facility, split in zip(facilities, table.column("split").to_pylist(), strict=True):
        splits.setdefault(facility, set()).add(split)
    mixed = sorted(f for f, s in splits.items() if len(s) > 1)
    if mixed:
        errors.append(f"every game of a facility shares one split: {', '.join(mixed)}")
    return errors


CATALOG = TableContract(CATALOG_SCHEMA, CatalogRow, _rules)
