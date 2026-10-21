"""Rally mode's marks: review, the saved file, and loading it back."""

import pytest
from pydantic import ValidationError

from dinkdata.contracts.rallies import RallyLabels
from dinkdata.studio.rally import (
    GameMark,
    IncompleteMarks,
    Marks,
    RallyMark,
    from_labels,
    review,
    to_labels,
)
from tests.contracts.examples import example

VIDEO_ID = "v_5eed00000000a001"


def rally(t: float, server: str, side: str, **fields) -> RallyMark:
    return RallyMark(t=t, end_t=t + 5.0, server=server, side=side, **fields)  # type: ignore[arg-type]


def one_game(*rallies: RallyMark, end_t: float | None = 100.0, finished: bool = False) -> Marks:
    return Marks(
        games=[GameMark(start_t=1.0, end_t=end_t, finished=finished)], rallies=list(rallies)
    )


def test_the_review_numbers_rallies_and_replays_the_score():
    marks = one_game(rally(10, "p1", "right"), rally(20, "p1", "left"), rally(30, "p3", "right"))
    result = review(marks)
    assert [v.id for v in result.rallies] == ["g1_r1", "g1_r2", "g1_r3"]
    assert [v.score_before for v in result.rallies] == ["0-0-2", "1-0-2", "0-1-1"]
    assert [v.winner_team for v in result.rallies] == ["A", "B", None]
    assert not any(v.red for v in result.rallies)
    assert result.games[0].final_score == {"A": 1, "B": 0}


def test_marks_in_any_order_are_reviewed_in_time_order():
    marks = one_game(rally(20, "p1", "left"), rally(10, "p1", "right"))
    assert [v.id for v in review(marks).rallies] == ["g1_r2", "g1_r1"]


def test_a_rule_break_is_red_until_the_labeller_marks_it():
    marks = one_game(rally(10, "p1", "left"), rally(20, "p1", "right"))
    view = review(marks).rallies[0]
    assert view.red
    assert view.missing == ["wrong_side"]
    assert "D to add wrong_side" in view.problems[0]

    marks.rallies[0].deviations.append("wrong_side")
    view = review(marks).rallies[0]
    assert not view.red
    assert view.suggested == ["wrong_side"]


def test_an_ambiguous_winner_is_red_and_lists_the_choices():
    marks = one_game(
        rally(10, "p1", "right"),
        rally(20, "p1", "left"),
        rally(30, "p3", "right"),
        rally(40, "p3", "right"),
    )
    view = review(marks).rallies[2]
    assert view.red
    assert view.winner_options == {"A": ["extra_serve"], "B": ["wrong_side"]}
    assert "Press A or B" in view.problems[0]


def test_unfinished_marks_are_to_do_not_red():
    marks = one_game(RallyMark(t=10.0), rally(20, "p1", "left"), end_t=None)
    result = review(marks)
    assert "Pick the server" in result.rallies[0].todo[0]
    assert "Press E" in result.rallies[0].todo[1]
    assert result.rallies[1].score_before is None
    assert "Press G" in result.games[0].todo[0]
    assert not any(v.red for v in result.rallies)


def test_a_serve_outside_every_game_is_to_do():
    marks = one_game(rally(200, "p1", "right"))
    assert "outside every game" in review(marks).rallies[0].todo[0]


def test_saving_incomplete_marks_lists_every_problem():
    marks = one_game(RallyMark(t=10.0), end_t=None)
    with pytest.raises(IncompleteMarks) as raised:
        to_labels(marks, VIDEO_ID, "marti")
    assert len(raised.value.problems) == 3


def test_every_rally_needs_the_labellers_winner():
    marks = one_game(rally(10, "p1", "right"), rally(20, "p1", "left"), finished=True)
    assert "Press A or B" in review(marks).rallies[0].todo[-1]
    marks.rallies[0].winner = "A"
    assert not review(marks).rallies[0].todo
    marks.rallies[1].replay = True
    assert not review(marks).rallies[1].todo


def test_a_cut_off_game_may_end_on_a_rally_without_a_winner():
    marks = one_game(rally(10, "p1", "right", winner="A"), rally(20, "p1", "left"))
    assert not review(marks).rallies[1].todo


def test_the_replay_checks_a_winner_instead_of_choosing_it():
    # In rally 2, p3 serves for B as server 1, and B wins. The players forget the point: p3
    # and p4 don't swap, and p4 serves rally 3 from the left. Left to the serves, the replay
    # would call rally 2 a loss with server 1 and quietly give it to A.
    marks = one_game(
        rally(10, "p1", "right", winner="B"), rally(20, "p3", "right"), rally(30, "p4", "left")
    )
    assert review(marks).rallies[1].winner_team == "A"
    marks.rallies[1].winner = "B"
    result = review(marks)
    assert result.rallies[1].winner_team == "B"
    # The deviation belongs to the serve that broke the rule.
    assert result.rallies[2].red
    assert "wrong_server" in result.rallies[2].missing


def test_the_contract_still_has_the_last_word():
    # A finished game that stops at 1-0 needs game_end_mismatch, which the contract checks.
    marks = one_game(rally(10, "p1", "right", winner="A"), finished=True)
    with pytest.raises(ValidationError, match="game_end_mismatch"):
        to_labels(marks, VIDEO_ID, "marti")
    marks.rallies[0].deviations.append("game_end_mismatch")
    labels = to_labels(marks, VIDEO_ID, "marti")
    assert labels.games[0].winner_team == "A"


def test_the_example_file_survives_loading_and_saving():
    data = example("rallies")
    # The labeller doesn't mark receivers, so the page's files have none.
    for game in data["games"]:
        for r in game["rallies"]:
            r["serve"]["receiver"] = None
    saved = RallyLabels.model_validate(data)
    marks = from_labels(saved)
    # Every winner is the labeller's own, so loading keeps them all. Only g2's last rally,
    # which the recording cut off, has none.
    assert [r.winner is None and not r.replay for r in marks.rallies].count(True) == 1
    assert marks.rallies[-1].winner is None
    assert to_labels(marks, saved.video_id, saved.labeller) == saved
