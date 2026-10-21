"""`rallies.json`, rally-level gold labels. Owner: Marti (docs/DESIGN.md sections 7 and 9).

The rally labeller is a browser page that can't land on exact frames, so labels store time as
`t` (ADR 0015). `start_frame` and `end_frame` stay null until a later step snaps each time to
the nearest frame in the video's frames.parquet.

Labels record what was played, including the score as played and each rule deviation. Only
gold keeps the score: it measures how often players get it wrong, and no output carries it
(ADR 0019). The labeller marks every rally's winner, so the score follows the winners and
never decides them.
"""

from typing import Literal

from pydantic import Field, model_validator

from dinkdata.contracts.common import (
    Conf,
    Frame,
    GameId,
    ScoreCall,
    Seconds,
    StrictModel,
    Team,
    VideoId,
    check_unique,
    parse_score_call,
    team_of,
)
from dinkdata.contracts.games import RallyBase, check_frames, check_game

RuleDeviationType = Literal[
    "wrong_server",
    "wrong_side",
    "extra_serve",
    "missed_side_out",
    "early_side_out",
    "game_end_mismatch",
]
Target = Literal[11, 15, 21]


class RuleDeviation(StrictModel):
    """A rule break by the players (GLOSSARY: Rule deviation). Gold labels only.

    wrong_server: the right team and server number, but the other partner served.
    wrong_side: the right player served from the wrong side.
    extra_serve: the serving team lost as server 1 and served again at the same call.
    missed_side_out: the serving team lost with server 2, or with the only server at 0-0-2,
    and kept the serve.
    early_side_out: the serving team lost with server 1, outside 0-0-2, and handed the serve to
    the other team, skipping server 2.
    game_end_mismatch: the players stopped at a score that doesn't end the game, or played on
    past one. Only on a game's last rally.
    """

    type: RuleDeviationType
    conf: Conf


class FinalScore(StrictModel):
    A: int = Field(ge=0)
    B: int = Field(ge=0)


class LabelRally(RallyBase):
    start_frame: Frame | None = None
    end_frame: Frame | None = None
    score_before: ScoreCall = Field(description="The score as played, with the server number.")
    rule_deviations: list[RuleDeviation]

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
        check_game(self.id, self.start_t, self.end_t, list(self.rallies))
        check_score(
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

    schema_: Literal["dinkdata.rallies/v2"] = Field(alias="schema")
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


def check_score(
    game_id: str,
    rallies: list[LabelRally],
    target: int,
    finished: bool,
    winner_team: Team | None,
    final_score: FinalScore,
) -> None:
    """The score as played must follow the labelled winners (DESIGN 6.10)."""
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


def _recount(rallies: list[LabelRally]) -> set[tuple[int, int]]:
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
