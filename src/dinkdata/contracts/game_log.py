"""`events.json`, the game log: one per recording (docs/DESIGN.md section 7).

Shared file. Marti owns `players`, `segments`, `games` and the rally fields in
`dinkdata.contracts.games`. Robby owns `video`, `camera` and the event list in
`dinkdata.contracts.events`, and the rally fields `winner_source`, `end_reason` and `events`.
"""

from typing import Literal

from pydantic import Field, model_validator

from dinkdata.contracts.common import (
    CameraId,
    Conf,
    Frame,
    GameId,
    PlayerId,
    StrictModel,
    Team,
    VideoId,
    check_unique,
    team_of,
)
from dinkdata.contracts.events import EndReason, Event, WinnerSource
from dinkdata.contracts.games import (
    FinalScore,
    RallyBase,
    Segment,
    Target,
    check_frames,
    check_game,
)


class Video(StrictModel):
    id: VideoId
    fps_nominal: float = Field(
        gt=0, description="The container's frame rate. Never use it for time."
    )
    frames: str = Field(min_length=1, description="Path of the video's frames.parquet.")
    dropped_frames: int = Field(ge=0)


class Camera(StrictModel):
    id: CameraId
    version: int = Field(ge=1, description="Calibration version in cameras/{id}/v{n}/.")


class Player(StrictModel):
    id: PlayerId
    team: Team
    label: str = Field(min_length=1, max_length=40, description="Generic, such as 'Player 1'.")
    crop: str | None = Field(description="Path of the photo crop, or null if none.")


class Rally(RallyBase):
    start_frame: Frame = Field(description="Frame of the serve.")
    end_frame: Frame = Field(description="Frame when the ball is dead.")
    winner_source: WinnerSource | None = Field(description="null when winner_team is null.")
    end_reason: EndReason | None = Field(description="null when unknown.")
    reviewed: bool = Field(description="true once a person has checked this rally.")
    conf: Conf
    events: list[Event]

    @model_validator(mode="after")
    def _events_inside(self) -> "Rally":
        check_frames(self.id, self.start_frame, self.end_frame)
        if (self.winner_team is None) != (self.winner_source is None):
            raise ValueError(f"{self.id}: set winner_source exactly when winner_team is set")
        times = [e.t for e in self.events]
        if times != sorted(times):
            raise ValueError(f"{self.id}: events must be sorted by t")
        for e in self.events:
            if not (
                self.start_t <= e.t <= self.end_t and self.start_frame <= e.frame <= self.end_frame
            ):
                raise ValueError(f"{e.id}: event must be inside rally {self.id}")
        return self


class Game(StrictModel):
    id: GameId
    format: Literal["sideout"]
    target: Target
    finished: bool = Field(description="false when the recording cut the game off.")
    winner_team: Team | None
    final_score: FinalScore
    rallies: list[Rally]

    @model_validator(mode="after")
    def _game_rules(self) -> "Game":
        check_game(
            self.id,
            list(self.rallies),
            self.target,
            self.finished,
            self.winner_team,
            self.final_score,
        )
        return self


class EventLog(StrictModel):
    """The game log of one recording. Rules JSON Schema can't express are checked in code."""

    schema_: Literal["dinkdata.events/v1"] = Field(alias="schema")
    video: Video
    camera: Camera
    players: list[Player] = Field(min_length=4, max_length=4)
    segments: list[Segment]
    games: list[Game]

    @property
    def video_id(self) -> str:
        return self.video.id

    @model_validator(mode="after")
    def _log_rules(self) -> "EventLog":
        check_unique([p.id for p in self.players], "player")
        for p in self.players:
            if p.team != team_of(p.id):
                raise ValueError(f"{p.id} must be on team {team_of(p.id)}")
        for before, after in zip(self.segments, self.segments[1:], strict=False):
            if after.start_frame <= before.end_frame or after.start_t < before.end_t:
                raise ValueError(
                    f"segments overlap or are out of order at frame {after.start_frame}"
                )
        check_unique([g.id for g in self.games], "game")
        rallies = [r for g in self.games for r in g.rallies]
        for before, after in zip(rallies, rallies[1:], strict=False):
            if after.start_frame <= before.end_frame or after.start_t < before.end_t:
                raise ValueError(f"rallies overlap or are out of order: {before.id}, {after.id}")
        check_unique([e.id for r in rallies for e in r.events], "event")
        return self
