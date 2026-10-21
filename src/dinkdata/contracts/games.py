"""Games, rallies and serves. Owner: Marti (docs/DESIGN.md 6.6, 6.9).

The game log (`events.json`) and the rally-level gold labels (`rallies.json`) share these
models, so the serve sequence and the eval read both the same way. Nothing here holds the
score: players often get it wrong, so no output carries it (ADR 0019). Only the gold labels in
`dinkdata.contracts.rallies` keep the score as played.
"""

from typing import Literal

from pydantic import Field, model_validator

from dinkdata.contracts.common import (
    Conf,
    Frame,
    PlayerId,
    RallyId,
    Seconds,
    Side,
    StrictModel,
    Team,
    check_span,
    check_unique,
    team_of,
)

SegmentType = Literal["game", "warmup", "drill", "idle"]


class Serve(StrictModel):
    """Who served, from where, and to whom. In gold labels `conf` is 1."""

    server: PlayerId
    side: Side = Field(description="The side of the court the server stood on.")
    receiver: PlayerId | None = Field(description="null when not visible.")
    conf: Conf

    @model_validator(mode="after")
    def _receiver_is_an_opponent(self) -> "Serve":
        if self.receiver is not None and team_of(self.receiver) == team_of(self.server):
            raise ValueError(f"receiver {self.receiver} is on the server's team")
        return self


class Segment(StrictModel):
    """A stretch of the recording with one game mode."""

    type: SegmentType
    start_frame: Frame
    end_frame: Frame
    start_t: Seconds
    end_t: Seconds
    conf: Conf

    @model_validator(mode="after")
    def _ordered(self) -> "Segment":
        check_span(self.start_frame, self.end_frame, f"{self.type} segment", "frame")
        check_span(self.start_t, self.end_t, f"{self.type} segment")
        return self


class RallyBase(StrictModel):
    """Fields every rally has, in the game log and in gold labels."""

    id: RallyId
    start_t: Seconds = Field(description="When the serve is hit.")
    end_t: Seconds = Field(description="When the ball is dead.")
    serve: Serve
    winner_team: Team | None = Field(description="null when unknown, and for a replay.")
    replay: bool = Field(description="The rally is replayed: same server and side.")

    @model_validator(mode="after")
    def _rally_rules(self) -> "RallyBase":
        check_span(self.start_t, self.end_t, self.id)
        if self.replay and self.winner_team is not None:
            raise ValueError(f"{self.id}: a replay has no winner_team")
        return self


def check_frames(rally_id: str, start: int | None, end: int | None) -> None:
    if (start is None) != (end is None):
        raise ValueError(f"{rally_id}: set both start_frame and end_frame, or neither")
    if start is not None and end is not None:
        check_span(start, end, rally_id, "frame")


def check_game(game_id: str, start_t: float, end_t: float, rallies: list[RallyBase]) -> None:
    """Rules across one game's rallies: ids, order, and every rally inside the game."""
    check_span(start_t, end_t, game_id)
    check_unique([r.id for r in rallies], "rally")
    for rally in rallies:
        if not rally.id.startswith(f"{game_id}_"):
            raise ValueError(
                f"rally {rally.id} is in game {game_id}, so its id must start {game_id}_"
            )
        if not start_t <= rally.start_t < rally.end_t <= end_t:
            raise ValueError(f"{rally.id} must be inside game {game_id}")
    for before, after in zip(rallies, rallies[1:], strict=False):
        if after.start_t < before.end_t:
            raise ValueError(f"rallies overlap or are out of order: {before.id}, {after.id}")
