"""`players.parquet`: player tracks, one row per frame per track. Owner: Marti (DESIGN 6.6).

The contract is the pyarrow schema `PLAYERS_SCHEMA`. `PlayerRow` describes one row for the
generated JSON Schema and for code that builds rows. Tracks that aren't one of the four
players stay in the table with `player_id` and `team` null, so a patch can reassign them.
Rows are sorted by frame, then track_id. Keypoints are the 17 COCO keypoints as (x, y, conf)
in pixels. A keypoint with conf 0 was not found.
"""

from pathlib import Path
from typing import Annotated

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import Field, model_validator

from dinkdata.contracts.common import Conf, Frame, PlayerId, Seconds, StrictModel, Team, team_of

SCHEMA_NAME = "dinkdata.players/v1"
KEYPOINTS = 17


def _fixed_list(item: pa.DataType, size: int) -> pa.DataType:
    # Parquet names list items "element", so the schema uses that name to survive a round trip.
    return pa.list_(pa.field("element", item), size)


PLAYERS_SCHEMA = pa.schema(
    [
        pa.field("frame", pa.int64(), nullable=False),
        pa.field("t", pa.float64(), nullable=False),
        pa.field("player_id", pa.string()),
        pa.field("track_id", pa.int32(), nullable=False),
        pa.field("team", pa.string()),
        pa.field("box", _fixed_list(pa.float32(), 4), nullable=False),
        pa.field("keypoints", _fixed_list(_fixed_list(pa.float32(), 3), KEYPOINTS), nullable=False),
        pa.field("foot_court", _fixed_list(pa.float32(), 2)),
        pa.field("estimated_foot", pa.bool_(), nullable=False),
        pa.field("conf", pa.float32(), nullable=False),
        pa.field("foot_conf", pa.float32()),
    ],
    metadata={"schema": SCHEMA_NAME},
)

Pixels = Annotated[float, Field(allow_inf_nan=False)]
Feet = Annotated[float, Field(allow_inf_nan=False)]
Keypoint = tuple[Pixels, Pixels, Conf]


class PlayerRow(StrictModel):
    """One row of players.parquet."""

    frame: Frame
    t: Seconds
    player_id: PlayerId | None = Field(description="null for a track that isn't a player.")
    track_id: int = Field(ge=0, le=2**31 - 1)
    team: Team | None = Field(description="Follows player_id: p1 and p2 are A.")
    box: tuple[Pixels, Pixels, Pixels, Pixels] = Field(description="x1, y1, x2, y2 in pixels.")
    keypoints: list[Keypoint] = Field(min_length=KEYPOINTS, max_length=KEYPOINTS)
    foot_court: tuple[Feet, Feet] | None = Field(
        description="Foot point in court feet. null when off the floor mapping or not visible."
    )
    estimated_foot: bool = Field(description="true when the foot point came from the hips.")
    conf: Conf = Field(description="Detection confidence.")
    foot_conf: Conf | None = Field(description="Foot point confidence. null with foot_court.")

    @model_validator(mode="after")
    def _row_rules(self) -> "PlayerRow":
        if self.player_id is None:
            if self.team is not None:
                raise ValueError("a track that isn't a player has no team")
        elif self.team != team_of(self.player_id):
            raise ValueError(f"{self.player_id} must be on team {team_of(self.player_id)}")
        x1, y1, x2, y2 = self.box
        if not (x2 > x1 and y2 > y1):
            raise ValueError(f"box {self.box} must be x1, y1, x2, y2 with x2 > x1 and y2 > y1")
        if (self.foot_court is None) != (self.foot_conf is None):
            raise ValueError("foot_conf is set exactly when foot_court is set")
        return self


def players_table(rows: list[PlayerRow]) -> pa.Table:
    return pa.Table.from_pylist([row.model_dump() for row in rows], schema=PLAYERS_SCHEMA)


def table_rows(table: pa.Table) -> list[PlayerRow]:
    return [PlayerRow.model_validate(row) for row in table.to_pylist()]


def players_errors(table: pa.Table) -> list[str]:
    """Everything wrong with a players table. Vectorised, so it is cheap on a whole game."""
    if not table.schema.equals(PLAYERS_SCHEMA, check_metadata=True):
        return [f"schema doesn't match {SCHEMA_NAME}:\n{table.schema}"]
    errors: list[str] = []
    for field in PLAYERS_SCHEMA:
        if not field.nullable and table.column(field.name).null_count:
            errors.append(f"{field.name} has nulls")
    if errors:
        return errors

    def column(name: str) -> np.ndarray:
        return table.column(name).to_numpy(zero_copy_only=False)

    def values(name: str, width: int) -> np.ndarray:
        array = table.column(name).combine_chunks()
        while pa.types.is_fixed_size_list(array.type):
            array = array.flatten()
        return array.to_numpy(zero_copy_only=False).reshape(len(table), width)

    frame, t, track = column("frame"), column("t"), column("track_id")
    d_frame, d_track, d_t = np.diff(frame), np.diff(track), np.diff(t)
    if np.any((d_frame < 0) | ((d_frame == 0) & (d_track < 0))):
        errors.append("rows must be sorted by frame, then track_id")
    if np.any((d_frame == 0) & (d_track == 0)):
        errors.append("duplicate (frame, track_id) rows")
    if np.any((frame < 0) | ~np.isfinite(t) | (t < 0)):
        errors.append("frame and t must be non-negative")
    elif np.any(((d_frame == 0) & (d_t != 0)) | ((d_frame > 0) & (d_t <= 0))):
        errors.append("t must be the same within a frame and rise with frame")

    conf = column("conf")
    kp_conf = values("keypoints", KEYPOINTS * 3)[:, 2::3]
    foot_conf = table.column("foot_conf").drop_null().to_numpy(zero_copy_only=False)
    for name, c in [("conf", conf), ("keypoint conf", kp_conf), ("foot_conf", foot_conf)]:
        if np.any(~((c >= 0) & (c <= 1))):
            errors.append(f"{name} must be between 0 and 1")
    if (
        table.column("foot_conf").is_null().to_pylist()
        != table.column("foot_court").is_null().to_pylist()
    ):
        errors.append("foot_conf is set exactly when foot_court is set")

    box = values("box", 4)
    if np.any(~((box[:, 2] > box[:, 0]) & (box[:, 3] > box[:, 1]))):
        errors.append("box must be x1, y1, x2, y2 with x2 > x1 and y2 > y1")

    players = table.column("player_id").to_pylist()
    teams = table.column("team").to_pylist()
    for player, team in set(zip(players, teams, strict=True)):
        if player is None and team is None:
            continue
        if player not in ("p1", "p2", "p3", "p4") or team != team_of(player):
            errors.append(f"player_id {player!r} with team {team!r} breaks the p1 to p4 convention")
    return errors


def read_players(path: Path) -> pa.Table:
    """Read players.parquet and validate it. Raises ValueError if it is invalid."""
    table = pq.read_table(path)
    errors = players_errors(table)
    if errors:
        raise ValueError(f"{path.name} is invalid: " + "; ".join(errors))
    return table


def write_players(table: pa.Table, path: Path) -> None:
    errors = players_errors(table)
    if errors:
        raise ValueError("players table is invalid: " + "; ".join(errors))
    pq.write_table(table, path)
