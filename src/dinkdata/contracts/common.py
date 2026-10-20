"""Types and helpers that every contract shares.

Time. `t` is seconds from the presentation timestamp (PTS) of the video's first frame:
`(pts - first_pts) * time_base`. For an MP4 this is the same number a browser's
`video.currentTime` reports, so tools without frame access (the rally labeller, the reel web
player) can write `t` directly. `frame` is the 0-based index of a decoded frame. Never derive
one from the other with a fixed frame rate, because PickleCam videos drop frames (ADR 0005).
"""

import json
import re
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

PlayerId = Literal["p1", "p2", "p3", "p4"]
Team = Literal["A", "B"]
Side = Literal["left", "right"]

Seconds = Annotated[
    float,
    Field(ge=0, allow_inf_nan=False, description="Seconds from the first frame's timestamp."),
]
Frame = Annotated[int, Field(ge=0, description="0-based index of a decoded frame.")]
Conf = Annotated[
    float,
    Field(ge=0, le=1, allow_inf_nan=False, description="Confidence, 0 to 1. Gold labels use 1."),
]

VIDEO_ID_PATTERN = r"^v_[0-9a-f]{16}$"
CAMERA_ID_PATTERN = r"^c_[0-9a-f]{16}$"
VideoId = Annotated[
    str, Field(pattern=VIDEO_ID_PATTERN, description="Opaque video id (dinkdata.contracts.ids).")
]
CameraId = Annotated[
    str, Field(pattern=CAMERA_ID_PATTERN, description="Opaque camera id (dinkdata.contracts.ids).")
]
GameId = Annotated[str, Field(pattern=r"^g[1-9][0-9]*$", description="g1, g2, ... in time order.")]
RallyId = Annotated[
    str, Field(pattern=r"^g[1-9][0-9]*_r[1-9][0-9]*$", description="g1_r1: game, then rally.")
]
ScoreCall = Annotated[
    str,
    Field(
        pattern=r"^[0-9]+-[0-9]+-[12]$",
        description="Score call before the serve: serving team, receiving team, server number.",
    ),
]

M = TypeVar("M", bound=BaseModel)

_TEAMS: dict[str, Team] = {"p1": "A", "p2": "A", "p3": "B", "p4": "B"}


class StrictModel(BaseModel):
    """Base for every contract model: unknown fields are errors."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def team_of(player: PlayerId) -> Team:
    """p1 and p2 are team A, p3 and p4 are team B (GLOSSARY: p1, p2, p3, p4)."""
    return _TEAMS[player]


def t_from_pts(pts: int, first_pts: int, time_base: Fraction) -> float:
    """`t` for a frame, from its PTS, the first frame's PTS and the stream's time base."""
    if pts < first_pts:
        raise ValueError(f"pts {pts} is before the first frame's pts {first_pts}")
    return float((pts - first_pts) * time_base)


_SCORE_CALL = re.compile(r"([0-9]+)-([0-9]+)-([12])")


def parse_score_call(call: str) -> tuple[int, int, int]:
    """'4-3-2' as (serving team score, receiving team score, server number)."""
    match = _SCORE_CALL.fullmatch(call)
    if match is None:
        raise ValueError(f"not a score call: {call!r}")
    serving, receiving, server = match.groups()
    return int(serving), int(receiving), int(server)


def check_unique(ids: list[str], what: str) -> None:
    seen: set[str] = set()
    for item in ids:
        if item in seen:
            raise ValueError(f"{what} ids must be unique: {item} appears twice")
        seen.add(item)


def check_span(start: float, end: float, what: str, name: str = "t") -> None:
    if not end > start:
        raise ValueError(f"{what}: end_{name} {end} must be after start_{name} {start}")


def to_json(model: BaseModel) -> str:
    """The file text for a contract: JSON field names, 2-space indent, trailing newline."""
    return json.dumps(model.model_dump(mode="json", by_alias=True), indent=2) + "\n"


def load(model: type[M], path: Path) -> M:
    """Read and validate a contract file. Raises pydantic.ValidationError if it is invalid."""
    return model.model_validate_json(path.read_text())


def dump(model: BaseModel, path: Path) -> None:
    """Validate a contract model again and write it."""
    type(model).model_validate(model.model_dump(by_alias=True))
    path.write_text(to_json(model))
