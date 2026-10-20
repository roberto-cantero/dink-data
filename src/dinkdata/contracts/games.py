"""Games, rallies, serves and the score as played. Owner: Marti (docs/DESIGN.md 6.6, 6.9, 6.10).

The game log (`events.json`) and the rally-level gold labels (`rallies.json`) share these
models, so the score decoder and the eval read both the same way.
"""

from typing import Literal

from pydantic import Field, model_validator

from dinkdata.contracts.common import (
    Conf,
    Frame,
    PlayerId,
    RallyId,
    ScoreCall,
    Seconds,
    Side,
    StrictModel,
    Team,
    check_span,
    check_unique,
    parse_score_call,
    team_of,
)

RuleDeviationType = Literal[
    "wrong_server", "wrong_side", "extra_serve", "missed_side_out", "game_end_mismatch"
]
SegmentType = Literal["game", "warmup", "drill", "idle"]
Target = Literal[11, 15, 21]


class Serve(StrictModel):
    """Who served, from where, and to whom. In gold labels `conf` is 1."""

    server: PlayerId
    server_number: Literal[1, 2] = Field(description="1 or 2, as played.")
    side: Side = Field(description="The side of the court the server stood on.")
    receiver: PlayerId | None = Field(description="null when not visible.")
    conf: Conf

    @model_validator(mode="after")
    def _receiver_is_an_opponent(self) -> "Serve":
        if self.receiver is not None and team_of(self.receiver) == team_of(self.server):
            raise ValueError(f"receiver {self.receiver} is on the server's team")
        return self


class RuleDeviation(StrictModel):
    """A rule break by the players (GLOSSARY: Rule deviation, ADR 0014).

    wrong_server: the right team and server number, but the other partner served.
    wrong_side: the right player served from the wrong side.
    extra_serve: the serving team lost as server 1 and served again at the same call.
    missed_side_out: the serving team lost with server 2, or with the only server at 0-0-2,
    and kept the serve.
    game_end_mismatch: the players stopped at a score that doesn't end the game, or played on
    past one. Only on a game's last rally.
    """

    type: RuleDeviationType
    conf: Conf


class FinalScore(StrictModel):
    A: int = Field(ge=0)
    B: int = Field(ge=0)


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
    score_before: ScoreCall
    winner_team: Team | None = Field(description="null when unknown, and for a replay.")
    replay: bool = Field(description="The rally is replayed: same server, side and score.")
    rule_deviations: list[RuleDeviation]

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


def check_game(
    game_id: str,
    rallies: list[RallyBase],
    target: int,
    finished: bool,
    winner_team: Team | None,
    final_score: FinalScore,
) -> None:
    """Rules across one game's rallies, including the score as played (DESIGN 6.9, 6.10)."""
    check_unique([r.id for r in rallies], "rally")
    for rally in rallies:
        if not rally.id.startswith(f"{game_id}_"):
            raise ValueError(
                f"rally {rally.id} is in game {game_id}, so its id must start {game_id}_"
            )
    for before, after in zip(rallies, rallies[1:], strict=False):
        if after.start_t < before.end_t:
            raise ValueError(f"rallies overlap or are out of order: {before.id}, {after.id}")
    for rally in rallies[:-1]:
        if any(d.type == "game_end_mismatch" for d in rally.rule_deviations):
            raise ValueError(f"{rally.id}: game_end_mismatch belongs on the game's last rally")

    final = (final_score.A, final_score.B)
    possible = _recount(rallies)
    if final not in possible:
        raise ValueError(f"{game_id}: final_score {final} doesn't fit the rallies won")

    if not finished:
        if winner_team is not None:
            raise ValueError(f"{game_id} was cut off, so its winner_team must be null")
        return
    if winner_team is None:
        raise ValueError(f"{game_id} is finished, so it needs a winner_team")
    won, lost = final if winner_team == "A" else (final_score.B, final_score.A)
    if won <= lost:
        raise ValueError(f"{game_id}: winner_team {winner_team} must be ahead in final_score")
    mismatch = bool(rallies) and any(
        d.type == "game_end_mismatch" for d in rallies[-1].rule_deviations
    )
    if not mismatch and won != max(target, lost + 2):
        raise ValueError(
            f"{game_id}: {won}-{lost} doesn't end a game to target {target}. "
            "Mark game_end_mismatch on the last rally if the players stopped there."
        )


def _recount(rallies: list[RallyBase]) -> set[tuple[int, int]]:
    """Points (A, B) after the rallies. A team scores when it wins a rally it served.

    An unknown winner allows both outcomes, and the next rally's call settles which one.
    """
    possible = {(0, 0)}
    for i, rally in enumerate(rallies):
        serving, receiving, _ = parse_score_call(rally.score_before)
        if i == 0 and rally.score_before != "0-0-2":
            raise ValueError(f"{rally.id}: a game starts at 0-0-2, not {rally.score_before}")
        team = team_of(rally.serve.server)
        called = (serving, receiving) if team == "A" else (receiving, serving)
        if called not in possible:
            expected = " or ".join(
                f"{a}-{b}" if team == "A" else f"{b}-{a}" for a, b in sorted(possible)
            )
            raise ValueError(
                f"{rally.id}: score_before {rally.score_before} doesn't fit the rallies won "
                f"so far (expected {expected}-n)"
            )
        a, b = called
        won = (a + 1, b) if team == "A" else (a, b + 1)
        if rally.replay or (rally.winner_team is not None and rally.winner_team != team):
            possible = {called}
        elif rally.winner_team == team:
            possible = {won}
        else:
            possible = {called, won}
    return possible
