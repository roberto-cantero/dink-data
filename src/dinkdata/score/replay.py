"""Score replay: the side-out rules run over serves that a person marked. Owner: Marti.

The rally labeller marks each serve's time, server and side. This module replays one game's
score from those marks (DESIGN 6.9). It fills in each rally's winner from the serve that
follows it, and it suggests a rule deviation wherever the serves break the rules (DESIGN 6.10).
Points follow the rallies as played: a team scores when it wins a rally it served (ADR 0014).

The rules, after a rally served by player s from side x with server number n:

| Outcome | Next serve |
|---|---|
| Serving team won | s again, from the other side, because the partners swapped |
| Lost with server 1 | s's partner as server 2, from the other side, where they stand |
| Lost with server 2, or at `0-0-2` | Side-out: the other team's right-side player, from the right |
| Replay | s again, from x, at the same score |

For each rally the replay tries every outcome the labeller left open and keeps the one whose
next serve breaks the fewest rules. When two outcomes tie, it leaves the winner to the
labeller and lists what each choice would mean. Team positions are learnt from the serves:
a team's first serve shows who stands on its right.

A serve by the wrong team is `missed_side_out` when the serving team kept a serve it should
have lost, and `early_side_out` when it gave up its second serve. A team that hands over the
serve after winning a point fits no deviation type, so that rally is marked unexplained.

The score decoder (M2) reuses these rules, and eval uses them to check gold files.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from dinkdata.contracts.common import PlayerId, Side, Team, team_of
from dinkdata.contracts.games import RuleDeviationType, Target

Outcome = Literal["won", "lost", "replay"]
WinnerSource = Literal["labeller", "next_serve", "game_end"]
ServerNumber = Literal[1, 2]

_PARTNER: dict[PlayerId, PlayerId] = {"p1": "p2", "p2": "p1", "p3": "p4", "p4": "p3"}
_FLIP: dict[Side, Side] = {"left": "right", "right": "left"}
_OTHER: dict[Team, Team] = {"A": "B", "B": "A"}

# A serve by the wrong team, when no deviation type covers it, costs more than any one
# deviation. Handing over the serve right after winning a point is the least likely story,
# so it costs the most.
_UNEXPLAINED = 10
_UNEXPLAINED_AFTER_A_POINT = 20


@dataclass(frozen=True)
class ServeMark:
    """One serve as the labeller marked it."""

    t: float
    server: PlayerId
    side: Side
    replay: bool = False
    winner: Team | None = None
    """The labeller's winner. None lets the next serve decide."""

    def __post_init__(self) -> None:
        if self.replay and self.winner is not None:
            raise ValueError(f"the serve at {self.t} s is a replay, so it has no winner")


@dataclass(frozen=True)
class ReplayedRally:
    score_before: str
    server_number: ServerNumber
    winner_team: Team | None
    winner_from: WinnerSource | None
    deviations: tuple[RuleDeviationType, ...] = ()
    """Rule deviations this rally's serve suggests, given the rally before it."""
    unexplained: bool = False
    """The serve breaks the rules in a way no deviation type covers."""
    winner_options: dict[Team, tuple[RuleDeviationType, ...]] = field(default_factory=dict)
    """When the serves can't show the winner: each choice and the deviations it implies."""

    @property
    def fits(self) -> bool:
        return not (self.deviations or self.unexplained or self.winner_options)


@dataclass(frozen=True)
class ReplayedGame:
    rallies: tuple[ReplayedRally, ...]
    final_score: tuple[int, int]
    """Points (A, B) after the last rally."""
    winner_team: Team | None


Context = Literal["start", "replay", "won", "lost_with_1", "side_out"]


@dataclass(frozen=True)
class _Expected:
    context: Context
    team: Team
    server: PlayerId | None
    """None when either player may serve: a game's first serve, or a side-out to a team
    whose positions aren't known yet."""
    side: Side
    number: ServerNumber
    side_out_server: PlayerId | None = None
    """After a loss with server 1: who would serve if the team gave up the serve early."""


@dataclass(frozen=True)
class _Check:
    deviations: tuple[RuleDeviationType, ...]
    number: ServerNumber
    unexplained: bool = False
    cost: int = 0


def replay_game(
    serves: Sequence[ServeMark], *, finished: bool, target: Target = 11
) -> ReplayedGame:
    """Replay one game from its serves, which start at `0-0-2`.

    A finished game ends on a point for the serving team, so its last rally's winner is
    filled in too. A cut-off game leaves it to the labeller.
    """
    for before, after in zip(serves, serves[1:], strict=False):
        if after.t <= before.t:
            raise ValueError(f"serves must be in time order: {before.t} s, then {after.t} s")
    if not serves:
        return ReplayedGame(rallies=(), final_score=(0, 0), winner_team=None)

    score: dict[Team, int] = {"A": 0, "B": 0}
    right: dict[Team, PlayerId | None] = {"A": None, "B": None}
    start = _Expected("start", team_of(serves[0].server), None, "right", 2)
    check = _check(start, serves[0], previous=None)
    rallies: list[ReplayedRally] = []
    ended_early = False

    for i, serve in enumerate(serves):
        team = team_of(serve.server)
        right[team] = serve.server if serve.side == "right" else _PARTNER[serve.server]
        score_before = f"{score[team]}-{score[_OTHER[team]]}-{check.number}"
        options: dict[Team, tuple[RuleDeviationType, ...]] = {}
        if i == len(serves) - 1:
            outcome, source = _last_outcome(serve, finished)
            next_check = check
        else:
            outcome, source, next_check, options = _choose(
                serve, check.number, right, serves[i + 1]
            )
        rallies.append(
            ReplayedRally(
                score_before=score_before,
                server_number=check.number,
                winner_team=_winner(team, outcome),
                winner_from=source,
                deviations=check.deviations,
                unexplained=check.unexplained,
                winner_options=options,
            )
        )
        if outcome == "won":
            score[team] += 1
            right[team] = _PARTNER[serve.server] if right[team] == serve.server else serve.server
            if i < len(serves) - 1 and _game_over(score["A"], score["B"], target):
                ended_early = True
        check = next_check

    final = (score["A"], score["B"])
    if ended_early or (finished and not _game_over(*final, target)):
        last = rallies[-1]
        rallies[-1] = replace(last, deviations=(*last.deviations, "game_end_mismatch"))
    winner: Team | None = None
    if finished and final[0] != final[1]:
        winner = "A" if final[0] > final[1] else "B"
    return ReplayedGame(rallies=tuple(rallies), final_score=final, winner_team=winner)


def _last_outcome(serve: ServeMark, finished: bool) -> tuple[Outcome | None, WinnerSource | None]:
    if serve.replay:
        return "replay", None
    if serve.winner is not None:
        return ("won" if serve.winner == team_of(serve.server) else "lost"), "labeller"
    if finished:
        return "won", "game_end"
    return None, None


def _choose(
    serve: ServeMark,
    number: ServerNumber,
    right: dict[Team, PlayerId | None],
    next_serve: ServeMark,
) -> tuple[Outcome | None, WinnerSource | None, _Check, dict[Team, tuple[RuleDeviationType, ...]]]:
    """The outcome of `serve`'s rally, judged by the serve after it."""
    team = team_of(serve.server)
    if serve.replay:
        outcomes: list[Outcome] = ["replay"]
    elif serve.winner is not None:
        outcomes = ["won" if serve.winner == team else "lost"]
    else:
        outcomes = ["won", "lost"]
    checks: dict[Outcome, _Check] = {
        o: _check(_expect(serve, number, right, o), next_serve, previous=serve) for o in outcomes
    }
    best = min(c.cost for c in checks.values())
    tied: list[Outcome] = [o for o, c in checks.items() if c.cost == best]

    if len(tied) == 1:
        outcome = tied[0]
        source: WinnerSource | None = None
        if outcome != "replay":
            source = "labeller" if serve.winner is not None else "next_serve"
        return outcome, source, checks[outcome], {}

    # The serves can't show the winner. Score it as a loss until the labeller decides, and
    # list what each choice would mean for the next serve.
    options: dict[Team, tuple[RuleDeviationType, ...]] = {
        _OTHER[team] if o == "lost" else team: checks[o].deviations for o in tied
    }
    return None, None, replace(checks["lost"], deviations=()), options


def _expect(
    serve: ServeMark, number: ServerNumber, right: dict[Team, PlayerId | None], outcome: Outcome
) -> _Expected:
    """The next serve under the rules, if `serve`'s rally had `outcome`."""
    team = team_of(serve.server)
    if outcome == "replay":
        return _Expected("replay", team, serve.server, serve.side, number)
    if outcome == "won":
        return _Expected("won", team, serve.server, _FLIP[serve.side], number)
    other = _OTHER[team]
    if number == 1:
        return _Expected(
            "lost_with_1", team, _PARTNER[serve.server], _FLIP[serve.side], 2, right[other]
        )
    return _Expected("side_out", other, right[other], "right", 1)


def _check(expected: _Expected, actual: ServeMark, previous: ServeMark | None) -> _Check:
    """The deviations `actual` shows against `expected`.

    At a side-out or a game's start the serve comes from the right, whoever serves.
    Otherwise each player serves from where they stand.
    """
    if team_of(actual.server) != expected.team:
        if expected.context == "side_out":
            return _Check(("missed_side_out",), number=2, cost=1)
        if expected.context == "lost_with_1":
            # The team skipped server 2. The other team's serve follows the side-out rules.
            other = team_of(actual.server)
            early = _Expected("side_out", other, expected.side_out_server, "right", 1)
            check = _check(early, actual, previous)
            return replace(
                check, deviations=("early_side_out", *check.deviations), cost=check.cost + 1
            )
        cost = _UNEXPLAINED_AFTER_A_POINT if expected.context == "won" else _UNEXPLAINED
        return _Check((), number=1, unexplained=True, cost=cost)

    deviations: list[RuleDeviationType] = []
    number = expected.number
    stands = expected.side
    fixed_side = expected.context in ("start", "side_out")
    if (
        expected.context == "lost_with_1"
        and previous is not None
        and actual.server == previous.server
    ):
        deviations.append("extra_serve")
        number, stands = 1, previous.side
    elif expected.server is not None and actual.server != expected.server:
        deviations.append("wrong_server")
        if not fixed_side:
            stands = _FLIP[expected.side]
    if actual.side != stands:
        deviations.append("wrong_side")
    return _Check(tuple(deviations), number=number, cost=len(deviations))


def _winner(team: Team, outcome: Outcome | None) -> Team | None:
    if outcome == "won":
        return team
    if outcome == "lost":
        return _OTHER[team]
    return None


def _game_over(a: int, b: int, target: int) -> bool:
    """A game ends when a team reaches the target with a 2-point lead."""
    high, low = max(a, b), min(a, b)
    return high == max(target, low + 2)
