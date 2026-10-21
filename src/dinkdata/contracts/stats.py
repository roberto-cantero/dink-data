"""`stats.json`: the v1 stats of one recording. Owner: Robby (docs/STATS.md).

One entry per game, subject and stat. A subject is a player (p1 to p4) or a team (A or B).
`games_won` covers the whole recording, so its `game` is null. Every other stat is per game.
An entry that doesn't ship keeps its `reason` and may have a null `value`.
"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from dinkdata.contracts.common import (
    Conf,
    GameId,
    PlayerId,
    RunId,
    StrictModel,
    Team,
    VideoId,
)
from dinkdata.contracts.game_log import EventLog

StatName = Literal[
    "final_score",
    "games_won",
    "rallies_won",
    "points_scored",
    "serve_in_pct",
    "serve_depth",
    "return_in_pct",
    "return_depth",
    "net_errors",
    "out_errors",
    "serve_faults",
    "winners",
    "landing_map",
]
TEAM_STATS = {"final_score", "games_won", "rallies_won", "points_scored"}
COUNT_STATS = TEAM_STATS | {"net_errors", "out_errors", "serve_faults", "winners"}
RATIO_STATS = {"serve_in_pct", "return_in_pct"}
DEPTH_STATS = {"serve_depth", "return_depth"}

Feet = Annotated[float, Field(allow_inf_nan=False)]
CourtPoint = tuple[Feet, Feet]
Reason = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", description="Such as no_serves.")]


class Depth(StrictModel):
    """Bounces by depth bucket (docs/STATS.md): deep is 5 ft or less from the baseline."""

    deep: int = Field(ge=0)
    medium: int = Field(ge=0)
    short: int = Field(ge=0)


class LandingMap(StrictModel):
    """Court positions in feet of the player's bounces (docs/COURT.md)."""

    serve: list[CourtPoint]
    return_: list[CourtPoint] = Field(alias="return")
    out_error: list[CourtPoint]


Value = int | float | Depth | LandingMap


class Stat(StrictModel):
    game: GameId | None = Field(description="null for games_won, which covers the recording.")
    subject: PlayerId | Team
    stat: StatName
    value: Value | None = Field(description="null only when not shipped.")
    num: int | None = Field(ge=0, description="Numerator, for percentages only.")
    den: int | None = Field(ge=0, description="Denominator, for percentages only.")
    conf: Conf
    shipped: bool
    reason: Reason | None = Field(description="Why it didn't ship. null when shipped.")

    @model_validator(mode="after")
    def _stat_rules(self) -> "Stat":
        name = f"{self.game or 'recording'} {self.subject} {self.stat}"
        if (self.subject in ("A", "B")) != (self.stat in TEAM_STATS):
            kind = "a team" if self.stat in TEAM_STATS else "a player"
            raise ValueError(f"{name}: {self.stat} is for {kind}")
        if (self.game is None) != (self.stat == "games_won"):
            raise ValueError(f"{name}: game is null for games_won only")
        if self.shipped and (self.value is None or self.reason is not None):
            raise ValueError(f"{name}: a shipped stat has a value and no reason")
        if not self.shipped and self.reason is None:
            raise ValueError(f"{name}: a stat that doesn't ship needs a reason")
        is_ratio = self.stat in RATIO_STATS
        if is_ratio != (self.num is not None and self.den is not None) or (
            (self.num is None) != (self.den is None)
        ):
            raise ValueError(f"{name}: num and den are set for percentages only")
        if self.value is not None:
            self._check_value(name)
        return self

    def _check_value(self, name: str) -> None:
        value = self.value
        if self.stat in COUNT_STATS:
            ok = isinstance(value, int) and value >= 0
        elif self.stat in RATIO_STATS:
            ok = isinstance(value, int | float) and 0 <= value <= 1
            if isinstance(value, int | float) and self.num is not None and self.den is not None:
                if self.num > self.den:
                    raise ValueError(f"{name}: num must not exceed den")
                if self.den and abs(value - self.num / self.den) > 1e-6:
                    raise ValueError(f"{name}: value must be num / den")
        elif self.stat in DEPTH_STATS:
            ok = isinstance(value, Depth)
        else:
            ok = isinstance(value, LandingMap)
        if not ok:
            raise ValueError(f"{name}: wrong kind of value for {self.stat}")


class Stats(StrictModel):
    """The stats of one recording from one pipeline run."""

    schema_: Literal["dinkdata.stats/v1"] = Field(alias="schema")
    video_id: VideoId
    run_id: RunId
    stats: list[Stat]

    @model_validator(mode="after")
    def _unique(self) -> "Stats":
        keys = [(s.game, s.subject, s.stat) for s in self.stats]
        if len(set(keys)) != len(keys):
            raise ValueError("one entry per game, subject and stat")
        return self


def check_stats(stats: Stats, log: EventLog) -> list[str]:
    """Rules between stats.json and the events.json it was computed from."""
    if stats.video_id != log.video.id:
        return [f"video_id {stats.video_id} doesn't match events.json's {log.video.id}"]
    games = {g.id for g in log.games}
    return [
        f"{s.game} {s.subject} {s.stat}: no such game in events.json"
        for s in stats.stats
        if s.game is not None and s.game not in games
    ]
