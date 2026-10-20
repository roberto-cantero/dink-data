"""Hits, bounces and net events inside a rally. Owner: Robby (docs/DESIGN.md 6.7, 6.8).

Provisional: copied from the DESIGN section 7 example so the game log validates end to end.
Robby owns these shapes and may change them in his part of Contracts v1 (#33).
"""

from typing import Annotated, Literal

from pydantic import Field

from dinkdata.contracts.common import Conf, Frame, PlayerId, Seconds, StrictModel

EventId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
EndReason = Literal["net", "out", "double_bounce", "unreturned", "fault", "unexplained"]
WinnerSource = Literal["serve_state", "ball", "label"]
Point = tuple[float, float]


class Hit(StrictModel):
    id: EventId
    type: Literal["hit"]
    frame: Frame
    t: Seconds
    player: PlayerId | None = Field(description="null when the hitter is unknown.")
    shot_index: int = Field(ge=1, description="1 is the serve, 2 the return.")
    volley: bool
    conf: Conf


class Bounce(StrictModel):
    id: EventId
    type: Literal["bounce"]
    frame: Frame
    t: Seconds
    image_xy: Point | None = Field(description="Pixels. null when out of frame.")
    court_xy: Point | None = Field(description="Feet (docs/COURT.md). null when not visible.")
    in_: bool | None = Field(alias="in", description="null when not visible.")
    close_call: bool
    conf: Conf


class Net(StrictModel):
    id: EventId
    type: Literal["net"]
    frame: Frame
    t: Seconds
    conf: Conf


Event = Annotated[Hit | Bounce | Net, Field(discriminator="type")]
