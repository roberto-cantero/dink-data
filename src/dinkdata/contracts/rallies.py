"""`rallies.json`, rally-level gold labels. Owner: Marti (docs/DESIGN.md sections 7 and 9).

The rally labeller is a browser page that can't land on exact frames, so labels store time as
`t` (ADR 0015). `start_frame` and `end_frame` stay null until a later step snaps each time to
the nearest frame in the video's frames.parquet. Labels record what was played, including each
rule deviation (ADR 0014).
"""

from typing import Literal

from pydantic import Field, model_validator

from dinkdata.contracts.common import (
    Frame,
    GameId,
    Seconds,
    StrictModel,
    Team,
    VideoId,
    check_span,
    check_unique,
)
from dinkdata.contracts.games import FinalScore, RallyBase, Target, check_frames, check_game


class LabelRally(RallyBase):
    start_frame: Frame | None = None
    end_frame: Frame | None = None

    @model_validator(mode="after")
    def _frames(self) -> "LabelRally":
        check_frames(self.id, self.start_frame, self.end_frame)
        return self


class LabelGame(StrictModel):
    id: GameId
    start_t: Seconds = Field(description="Where the labeller marked the game's start.")
    end_t: Seconds = Field(description="Where the game ended or the recording cut it off.")
    target: Target
    finished: bool = Field(description="false when the recording cut the game off.")
    winner_team: Team | None
    final_score: FinalScore
    rallies: list[LabelRally]

    @model_validator(mode="after")
    def _game_rules(self) -> "LabelGame":
        check_span(self.start_t, self.end_t, self.id)
        for r in self.rallies:
            if not self.start_t <= r.start_t < r.end_t <= self.end_t:
                raise ValueError(f"{r.id} must be inside game {self.id}")
        check_game(
            self.id,
            list(self.rallies),
            self.target,
            self.finished,
            self.winner_team,
            self.final_score,
        )
        return self


class RallyLabels(StrictModel):
    """Rally-level gold for one recording, by one labeller."""

    schema_: Literal["dinkdata.rallies/v1"] = Field(alias="schema")
    video_id: VideoId
    labeller: str = Field(
        pattern=r"^[a-z][a-z0-9_-]{0,31}$",
        description="The labeller's short handle, as in labels/gold-rallies/{video_id}/{labeller}.",
    )
    games: list[LabelGame]

    @model_validator(mode="after")
    def _label_rules(self) -> "RallyLabels":
        check_unique([g.id for g in self.games], "game")
        for before, after in zip(self.games, self.games[1:], strict=False):
            if after.start_t < before.end_t:
                raise ValueError(f"games overlap or are out of order: {before.id}, {after.id}")
        return self
