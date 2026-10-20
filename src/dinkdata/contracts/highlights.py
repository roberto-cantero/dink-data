"""`highlights.json`, one reel per game per player. Owner: Marti (docs/DESIGN.md 3.3, 6.12).

A reel is a list of clips played from PickleCam's video (ADR 0012). The MP4 exists only when a
player asked for one. The marker and the title card come from players.parquet, events.json
and the photo crops, so this file doesn't repeat them.
"""

from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from dinkdata.contracts.common import (
    Frame,
    GameId,
    PlayerId,
    RallyId,
    Seconds,
    StrictModel,
    VideoId,
    check_span,
    check_unique,
)
from dinkdata.contracts.game_log import EventLog
from dinkdata.contracts.games import check_frames
from dinkdata.contracts.rallies import RallyLabels

ClipReason = Literal[
    "long_rally", "serve_point", "game_point", "final_rally", "winner", "ace", "dink_exchange"
]
ClipId = Annotated[str, Field(pattern=r"^g[1-9][0-9]*_p[1-4]_c[1-9][0-9]*$")]


class Clip(StrictModel):
    """One rally's stretch of video, with padding (DESIGN 3.3)."""

    id: ClipId
    rally_id: RallyId
    start_t: Seconds
    end_t: Seconds
    start_frame: Frame | None = None
    end_frame: Frame | None = None
    reasons: list[ClipReason] = Field(min_length=1)
    score: float = Field(ge=0, allow_inf_nan=False, description="The selector's score.")

    @model_validator(mode="after")
    def _clip_rules(self) -> "Clip":
        check_span(self.start_t, self.end_t, self.id)
        check_frames(self.id, self.start_frame, self.end_frame)
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError(f"{self.id}: reasons must be unique")
        return self


class Mp4(StrictModel):
    path: str = Field(description="Relative path of the rendered MP4 in the bucket.")
    rendered_at: AwareDatetime

    @field_validator("path")
    @classmethod
    def _relative_mp4(cls, path: str) -> str:
        parts = PurePosixPath(path)
        if parts.is_absolute() or ".." in parts.parts or parts.suffix != ".mp4" or "\\" in path:
            raise ValueError(f"path must be a relative .mp4 path inside the bucket: {path!r}")
        return path


class Reel(StrictModel):
    game_id: GameId
    player_id: PlayerId
    clips: list[Clip] = Field(min_length=1, description="In time order.")
    mp4: Mp4 | None = Field(description="null until a player asks for the MP4.")

    @model_validator(mode="after")
    def _reel_rules(self) -> "Reel":
        prefix = f"{self.game_id}_{self.player_id}_"
        for clip in self.clips:
            if not clip.id.startswith(prefix):
                raise ValueError(f"clip {clip.id} is in this reel, so its id must start {prefix}")
            if not clip.rally_id.startswith(f"{self.game_id}_"):
                raise ValueError(f"{clip.id}: rally {clip.rally_id} must be in {self.game_id}_")
        for before, after in zip(self.clips, self.clips[1:], strict=False):
            if after.start_t < before.start_t:
                raise ValueError(f"clips must be in time order: {before.id}, {after.id}")
            if after.start_t < before.end_t:
                raise ValueError(f"clips overlap: {before.id}, {after.id}")
        return self


class Highlights(StrictModel):
    """The reels of one recording."""

    schema_: Literal["dinkdata.highlights/v1"] = Field(alias="schema")
    video_id: VideoId
    reels: list[Reel]

    @model_validator(mode="after")
    def _highlights_rules(self) -> "Highlights":
        keys = [f"{r.game_id}/{r.player_id}" for r in self.reels]
        if len(set(keys)) != len(keys):
            raise ValueError("there is one reel per game and player")
        check_unique([c.id for r in self.reels for c in r.clips], "clip")
        return self


def check_highlights(highlights: Highlights, timeline: EventLog | RallyLabels) -> list[str]:
    """Rules between highlights.json and the rallies it cuts, from events.json or rallies.json.

    Each clip must contain its whole rally and end before the next rally's serve.
    """
    if highlights.video_id != timeline.video_id:
        return [f"video_id {highlights.video_id} doesn't match the timeline's {timeline.video_id}"]
    errors: list[str] = []
    rallies = [(g.id, r) for g in timeline.games for r in g.rallies]
    index = {r.id: i for i, (_, r) in enumerate(rallies)}
    games = {g.id for g in timeline.games}
    for reel in highlights.reels:
        if reel.game_id not in games:
            errors.append(f"{reel.game_id}: no such game in the timeline")
            continue
        for clip in reel.clips:
            i = index.get(clip.rally_id)
            if i is None or rallies[i][0] != reel.game_id:
                errors.append(f"{clip.id}: rally {clip.rally_id} is not in game {reel.game_id}")
                continue
            rally = rallies[i][1]
            if clip.start_t > rally.start_t or clip.end_t < rally.end_t:
                errors.append(f"{clip.id}: doesn't contain the whole rally {rally.id}")
            if i + 1 < len(rallies) and clip.end_t >= rallies[i + 1][1].start_t:
                errors.append(f"{clip.id}: runs into the next serve ({rallies[i + 1][1].id})")
    return errors
