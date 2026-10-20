"""Rally mode: the page's marks, checked against the rules and turned into `rallies.json`.

The page only records key presses as marks. This module groups the rallies into games,
replays each game's score with `dinkdata.score.replay`, says which rallies break the rules,
and builds a `RallyLabels` file that the contract validates (DESIGN 6.13 and 9).
"""

from pydantic import BaseModel, Field

from dinkdata.contracts.common import PlayerId, Seconds, Side, StrictModel, Team
from dinkdata.contracts.games import RuleDeviationType, Target
from dinkdata.contracts.rallies import RallyLabels
from dinkdata.score.replay import ReplayedGame, ReplayedRally, ServeMark, replay_game


class RallyMark(StrictModel):
    """One rally as the labeller marked it. `t` is the serve."""

    t: Seconds
    end_t: Seconds | None = None
    server: PlayerId | None = None
    side: Side | None = None
    replay: bool = False
    winner: Team | None = Field(default=None, description="Set only when the labeller chose.")
    deviations: list[RuleDeviationType] = Field(default_factory=list)


class GameMark(StrictModel):
    start_t: Seconds
    end_t: Seconds | None = None
    finished: bool = True
    target: Target = 11


class Marks(StrictModel):
    """Everything the labeller has marked in one recording."""

    games: list[GameMark] = Field(default_factory=list)
    rallies: list[RallyMark] = Field(default_factory=list)


class RallyView(BaseModel):
    """What the page shows for one rally, in the order of `Marks.rallies`."""

    id: str | None = None
    score_before: str | None = None
    server_number: int | None = None
    winner_team: Team | None = None
    winner_from: str | None = None
    suggested: list[RuleDeviationType] = Field(default_factory=list)
    missing: list[RuleDeviationType] = Field(
        default_factory=list, description="Suggested deviations the labeller hasn't marked."
    )
    winner_options: dict[Team, list[RuleDeviationType]] = Field(default_factory=dict)
    red: bool = Field(default=False, description="The score doesn't fit the rules here.")
    problems: list[str] = Field(
        default_factory=list, description="Why the rally is red. A save is still allowed."
    )
    todo: list[str] = Field(
        default_factory=list, description="Marks still missing. A save waits for them."
    )


class GameView(BaseModel):
    id: str
    final_score: dict[Team, int]
    winner_team: Team | None
    todo: list[str] = Field(default_factory=list)


class Review(BaseModel):
    rallies: list[RallyView]
    games: list[GameView]


class IncompleteMarks(ValueError):
    """The marks can't become a label file yet."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def review(marks: Marks) -> Review:
    """Replay every game and say, rally by rally, what fits the rules and what doesn't."""
    views = [RallyView() for _ in marks.rallies]
    games: list[GameView] = []
    in_game: set[int] = set()

    for n, (game, members) in enumerate(_group(marks), 1):
        game_id = f"g{n}"
        in_game.update(members)
        complete = _complete_prefix(marks, members)
        replayed = _replay(marks, game, complete)
        for k, i in enumerate(members, 1):
            view = views[i]
            view.id = f"{game_id}_r{k}"
            mark = marks.rallies[i]
            if mark.server is None or mark.side is None:
                view.todo.append("Pick the server (1 to 4) and the side (L or R).")
            if mark.end_t is None:
                view.todo.append("Press E when the ball is dead.")
            elif mark.end_t <= mark.t:
                view.todo.append("The rally ends before its serve. Press E again.")
        for i, rally in zip(complete, replayed.rallies, strict=True):
            _fill(views[i], marks.rallies[i], rally)
        todo = []
        if game.end_t is None:
            todo.append("Press G at the end of the game, or Shift+G if the recording cut it off.")
        if len(complete) < len(members):
            todo.append("The score stops at the first rally without a server and side.")
        games.append(
            GameView(
                id=game_id,
                final_score={"A": replayed.final_score[0], "B": replayed.final_score[1]},
                winner_team=replayed.winner_team,
                todo=todo,
            )
        )

    for i, view in enumerate(views):
        if i not in in_game:
            view.todo.append("This serve is outside every game. Press G to start one first.")
    return Review(rallies=views, games=games)


def to_labels(marks: Marks, video_id: str, labeller: str) -> RallyLabels:
    """The `rallies.json` model for the marks. Raises IncompleteMarks or ValidationError."""
    problems = [
        f"{v.id or f'the serve at {marks.rallies[i].t:.1f} s'}: {note}"
        for i, v in enumerate(review(marks).rallies)
        for note in v.todo
    ]
    problems += [
        f"the game from {g.start_t:.1f} s has no end. Press G or Shift+G."
        for g in marks.games
        if g.end_t is None
    ]
    if problems:
        raise IncompleteMarks(problems)

    games = []
    for n, (game, members) in enumerate(_group(marks), 1):
        replayed = _replay(marks, game, members)
        rallies = []
        for k, (i, rally) in enumerate(zip(members, replayed.rallies, strict=True), 1):
            mark = marks.rallies[i]
            rallies.append(
                {
                    "id": f"g{n}_r{k}",
                    "start_t": mark.t,
                    "end_t": mark.end_t,
                    "serve": {
                        "server": mark.server,
                        "server_number": rally.server_number,
                        "side": mark.side,
                        # The labeller doesn't mark receivers.
                        "receiver": None,
                        "conf": 1.0,
                    },
                    "score_before": rally.score_before,
                    "winner_team": rally.winner_team,
                    "replay": mark.replay,
                    "rule_deviations": [{"type": d, "conf": 1.0} for d in mark.deviations],
                }
            )
        games.append(
            {
                "id": f"g{n}",
                "start_t": game.start_t,
                "end_t": game.end_t,
                "target": game.target,
                "finished": game.finished,
                "winner_team": replayed.winner_team,
                "final_score": {"A": replayed.final_score[0], "B": replayed.final_score[1]},
                "rallies": rallies,
            }
        )
    return RallyLabels.model_validate(
        {
            "schema": "dinkdata.rallies/v1",
            "video_id": video_id,
            "labeller": labeller,
            "games": games,
        }
    )


def from_labels(labels: RallyLabels) -> Marks:
    """Marks for a saved file, so a labeller can carry on where they stopped.

    A winner becomes the labeller's choice only where the serves alone would say otherwise.
    """
    marks = Marks()
    for game in labels.games:
        marks.games.append(
            GameMark(
                start_t=game.start_t,
                end_t=game.end_t,
                finished=game.finished,
                target=game.target,
            )
        )
        rallies = [
            RallyMark(
                t=r.start_t,
                end_t=r.end_t,
                server=r.serve.server,
                side=r.serve.side,
                replay=r.replay,
                deviations=[d.type for d in r.rule_deviations],
            )
            for r in game.rallies
        ]
        serves = [
            ServeMark(t=m.t, server=r.serve.server, side=r.serve.side, replay=m.replay)
            for m, r in zip(rallies, game.rallies, strict=True)
        ]
        replayed = replay_game(serves, finished=game.finished, target=game.target)
        for mark, saved, auto in zip(rallies, game.rallies, replayed.rallies, strict=True):
            if saved.winner_team != auto.winner_team:
                mark.winner = saved.winner_team
        marks.rallies.extend(rallies)
    return marks


def _group(marks: Marks) -> list[tuple[GameMark, list[int]]]:
    """Each game in time order, with the indices of the rallies whose serve is inside it."""
    order = sorted(range(len(marks.rallies)), key=lambda i: marks.rallies[i].t)
    groups = []
    for game in sorted(marks.games, key=lambda g: g.start_t):
        end = float("inf") if game.end_t is None else game.end_t
        groups.append((game, [i for i in order if game.start_t <= marks.rallies[i].t < end]))
    return groups


def _complete_prefix(marks: Marks, members: list[int]) -> list[int]:
    complete = []
    for i in members:
        mark = marks.rallies[i]
        if mark.server is None or mark.side is None:
            break
        complete.append(i)
    return complete


def _replay(marks: Marks, game: GameMark, members: list[int]) -> ReplayedGame:
    serves = []
    for i in members:
        mark = marks.rallies[i]
        assert mark.server is not None and mark.side is not None
        serves.append(
            ServeMark(
                t=mark.t,
                server=mark.server,
                side=mark.side,
                replay=mark.replay,
                winner=None if mark.replay else mark.winner,
            )
        )
    # A game without an end yet is still being played, so its last winner stays open.
    finished = game.finished and game.end_t is not None
    return replay_game(serves, finished=finished, target=game.target)


def _fill(view: RallyView, mark: RallyMark, rally: ReplayedRally) -> None:
    view.score_before = rally.score_before
    view.server_number = rally.server_number
    view.winner_team = rally.winner_team
    view.winner_from = rally.winner_from
    view.suggested = list(rally.deviations)
    view.missing = [d for d in rally.deviations if d not in mark.deviations]
    view.winner_options = {team: list(d) for team, d in rally.winner_options.items()}
    if view.missing:
        view.problems.append(
            "The score doesn't fit the rules here. Fix the marks, or press D to add "
            + ", ".join(view.missing)
            + "."
        )
    if rally.unexplained:
        view.problems.append(
            "The serve went to the other team when the rules don't allow it, and no deviation "
            "type covers that. Check this serve and the one before it."
        )
    if view.winner_options:
        choices = "; ".join(
            f"{team} means {', '.join(d) or 'no deviation'} on the next rally"
            for team, d in sorted(view.winner_options.items())
        )
        view.problems.append(f"The serves can't show the winner. Press A or B ({choices}).")
    view.red = bool(view.missing or rally.unexplained or view.winner_options)
