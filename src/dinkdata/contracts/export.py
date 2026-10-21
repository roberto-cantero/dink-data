"""Generate the JSON Schemas in contracts/ from the pydantic models.

`uv run dink contracts export` writes them. A test fails when a committed schema differs from
a freshly generated one, so CI catches stale schemas.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from dinkdata.contracts.ball import BallLabelRow, BallRow
from dinkdata.contracts.camera import CameraCalibration
from dinkdata.contracts.candidates import CandidateRow
from dinkdata.contracts.catalog import CatalogRow
from dinkdata.contracts.frames import FrameRow
from dinkdata.contracts.game_log import EventLog
from dinkdata.contracts.highlights import Highlights
from dinkdata.contracts.patch import Patch
from dinkdata.contracts.players import PlayerRow
from dinkdata.contracts.rallies import RallyLabels
from dinkdata.contracts.stats import Stats

BASE_URL = "https://github.com/roberto-cantero/dink-data/contracts"
COMMENT = (
    "Generated from src/dinkdata/contracts/ by `uv run dink contracts export`. Don't edit by "
    "hand. Rules JSON Schema can't express, such as ordering, ids and the score, are checked "
    "by the pydantic models."
)

SOURCES: dict[str, tuple[Any, str]] = {
    "events": (EventLog, "DinkData game log (events.json)"),
    "rallies": (RallyLabels, "DinkData rally-level gold labels (rallies.json)"),
    "highlights": (Highlights, "DinkData highlight reels (highlights.json)"),
    "players": (list[PlayerRow], "DinkData player tracks (players.parquet rows)"),
    "catalog": (list[CatalogRow], "DinkData video catalog (catalog.parquet rows)"),
    "frames": (list[FrameRow], "DinkData frame timestamps (frames.parquet rows)"),
    "camera": (CameraCalibration, "DinkData camera calibration (camera.json)"),
    "ball": (list[BallRow], "DinkData ball track (ball.parquet rows)"),
    "candidates": (list[CandidateRow], "DinkData event candidates (candidates.parquet rows)"),
    "ball_labels": (list[BallLabelRow], "DinkData ball clicks (ball_labels.parquet rows)"),
    "stats": (Stats, "DinkData per-player stats (stats.json)"),
    "patch": (Patch, "DinkData corrections to a run (patch.json)"),
}


def generate_schemas() -> dict[str, str]:
    """The text of each contracts/{name}.schema.json."""
    out: dict[str, str] = {}
    for name, (source, title) in SOURCES.items():
        schema = TypeAdapter(source).json_schema()
        schema.pop("title", None)
        full = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"{BASE_URL}/{name}.schema.json",
            "title": title,
            "$comment": COMMENT,
            **schema,
        }
        out[name] = json.dumps(full, indent=2) + "\n"
    return out


def write_schemas(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, text in generate_schemas().items():
        path = directory / f"{name}.schema.json"
        path.write_text(text)
        paths.append(path)
    return paths


def stale_schemas(directory: Path) -> list[str]:
    """Names whose committed schema is missing or differs from the generated one."""
    return [
        name
        for name, text in generate_schemas().items()
        if not (directory / f"{name}.schema.json").exists()
        or (directory / f"{name}.schema.json").read_text() != text
    ]
