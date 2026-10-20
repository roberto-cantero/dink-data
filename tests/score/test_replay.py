"""Score replay over hand-written serve lists (DESIGN 6.9 and 6.10)."""

import pytest

from dinkdata.contracts.rallies import RallyLabels
from dinkdata.score.replay import ServeMark, replay_game
from tests.contracts.examples import example


def serves(*marks: str, **overrides: dict) -> list[ServeMark]:
    """'p1 R', 'p3 L' and so on, 10 s apart. `overrides` maps 'r3' to extra ServeMark fields."""
    out = []
    for n, mark in enumerate(marks, 1):
        server, side = mark.split()
        extra = overrides.get(f"r{n}", {})
        out.append(
            ServeMark(t=10.0 * n, server=server, side={"R": "right", "L": "left"}[side], **extra)  # type: ignore[arg-type]
        )
    return out


def calls(game) -> list[str]:
    return [r.score_before for r in game.rallies]


def winners(game) -> list[str | None]:
    return [r.winner_team for r in game.rallies]


def test_clean_side_out_scoring():
    game = replay_game(
        serves(
            "p1 R",  # 0-0-2, A wins: p1 and p2 swap, p1 serves again from the left
            "p1 L",  # A loses with the only server at 0-0-2: side-out
            "p3 R",  # B wins
            "p3 L",  # B loses with server 1: partner p4 serves from where they stand
            "p4 R",  # B loses with server 2: side-out to p2, on A's right since the swap
            "p2 R",
        ),
        finished=False,
    )
    assert calls(game) == ["0-0-2", "1-0-2", "0-1-1", "1-1-1", "1-1-2", "1-1-1"]
    assert winners(game) == ["A", "B", "B", "A", "A", None]
    assert [r.server_number for r in game.rallies] == [2, 2, 1, 1, 2, 1]
    assert all(r.fits for r in game.rallies)
    assert game.final_score == (1, 1)


def test_winners_come_from_the_next_serve():
    game = replay_game(serves("p1 R", "p1 L", "p3 R"), finished=False)
    assert [r.winner_from for r in game.rallies] == ["next_serve", "next_serve", None]


def test_a_replay_keeps_server_side_and_score():
    game = replay_game(serves("p1 R", "p1 L", "p1 L", "p1 R", r2={"replay": True}), finished=False)
    assert calls(game) == ["0-0-2", "1-0-2", "1-0-2", "2-0-2"]
    assert winners(game) == ["A", None, "A", None]
    assert all(r.fits for r in game.rallies)


def test_the_example_game_replays_to_the_committed_labels():
    labels = RallyLabels.model_validate(example("rallies"))
    g1 = labels.games[0]
    marks = [
        ServeMark(
            t=r.start_t,
            server=r.serve.server,
            side=r.serve.side,
            replay=r.replay,
            # g1_r8 is the one rally whose winner the serves can't show.
            winner=r.winner_team if r.id == "g1_r8" else None,
        )
        for r in g1.rallies
    ]
    game = replay_game(marks, finished=True, target=g1.target)
    assert calls(game) == [r.score_before for r in g1.rallies]
    assert winners(game) == [r.winner_team for r in g1.rallies]
    assert [r.server_number for r in game.rallies] == [r.serve.server_number for r in g1.rallies]
    assert [list(r.deviations) for r in game.rallies] == [
        [d.type for d in r.rule_deviations] for r in g1.rallies
    ]
    assert game.final_score == (g1.final_score.A, g1.final_score.B)
    assert game.winner_team == "A"
    assert game.rallies[-1].winner_from == "game_end"


def test_the_first_serve_comes_from_the_right():
    game = replay_game(serves("p1 L", "p1 R"), finished=False)
    assert game.rallies[0].deviations == ("wrong_side",)


B_SIDES_OUT = ("p1 R", "p1 L", "p3 R", "p3 L", "p4 R")  # then A serves at 1-1-1


def test_side_out_to_the_wrong_partner_is_wrong_server():
    # p2 stands on A's right after the swap at 1-0-2, so p1 should not serve.
    game = replay_game(serves(*B_SIDES_OUT, "p1 R"), finished=False)
    assert game.rallies[5].deviations == ("wrong_server",)
    assert game.rallies[4].winner_team == "A"
    assert calls(game)[5] == "1-1-1"


def test_side_out_from_the_left_is_wrong_side():
    game = replay_game(serves(*B_SIDES_OUT, "p2 L"), finished=False)
    assert game.rallies[5].deviations == ("wrong_side",)
    assert game.rallies[4].winner_team == "A"


def test_the_wrong_partner_serving_from_where_they_stand_is_one_deviation():
    # A wins at 1-1-1, so p2 and p1 swap: p2 should serve from the left, p1 stands right.
    # The serves alone could also be a loss with p1 on the wrong side, so the labeller says A.
    game = replay_game(serves(*B_SIDES_OUT, "p2 R", "p1 R", r6={"winner": "A"}), finished=False)
    assert game.rallies[6].deviations == ("wrong_server",)
    assert game.rallies[5].winner_team == "A"
    assert calls(game)[6] == "2-1-1"


def test_the_same_server_and_side_again_needs_the_labeller():
    game = replay_game(serves("p1 R", "p1 L", "p3 R", "p3 R"), finished=False)
    rally = game.rallies[2]
    assert rally.winner_team is None
    assert rally.winner_options == {"B": ("wrong_side",), "A": ("extra_serve",)}
    assert not rally.fits


def test_the_labeller_settles_an_extra_serve():
    game = replay_game(serves("p1 R", "p1 L", "p3 R", "p3 R", r3={"winner": "A"}), finished=False)
    assert game.rallies[2].winner_from == "labeller"
    assert game.rallies[3].deviations == ("extra_serve",)
    assert calls(game)[3] == "0-1-1"


def test_keeping_the_serve_after_losing_with_server_2_is_missed_side_out():
    game = replay_game(serves("p1 R", "p2 R", r1={"winner": "B"}), finished=False)
    assert game.rallies[1].deviations == ("missed_side_out",)
    assert calls(game)[1] == "0-0-2"


def test_a_winner_against_the_serves_is_flagged():
    game = replay_game(serves("p1 R", "p1 L", r1={"winner": "B"}), finished=False)
    assert game.rallies[1].deviations == ("missed_side_out",)
    assert game.rallies[0].winner_team == "B"


def test_giving_up_the_second_serve_has_no_deviation_type():
    # B loses with server 1, so p4 should serve, but A takes the serve.
    game = replay_game(serves("p1 R", "p1 L", "p3 R", "p2 R"), finished=False)
    rally = game.rallies[3]
    assert rally.unexplained
    assert rally.deviations == ()
    assert not rally.fits
    assert game.rallies[2].winner_team == "A"


def test_positions_are_learnt_at_a_teams_first_serve():
    # B's first side-out: p4 serves from the right, so p4 stands right for later side-outs.
    game = replay_game(
        serves("p1 R", "p1 L", "p4 R", "p3 L", "p2 R", "p2 L", "p1 R", "p3 R"), finished=False
    )
    assert calls(game) == ["0-0-2", "1-0-2", "0-1-1", "0-1-2", "1-0-1", "2-0-1", "2-0-2", "0-2-1"]
    assert game.rallies[7].deviations == ("wrong_server",)


def test_a_finished_game_ends_on_a_point_for_the_server():
    game = replay_game(serves("p1 R"), finished=True, target=11)
    assert game.rallies[0].winner_team == "A"
    assert game.rallies[0].winner_from == "game_end"
    assert game.final_score == (1, 0)
    assert game.rallies[0].deviations == ("game_end_mismatch",)


def test_a_cut_off_game_leaves_the_last_winner_open():
    game = replay_game(serves("p1 R", "p1 L"), finished=False)
    assert game.rallies[-1].winner_team is None
    assert game.final_score == (1, 0)
    assert game.winner_team is None
    assert game.rallies[-1].fits


def game_to(points_a: int, points_b: int) -> list[str]:
    """A wins `points_a` on p1's serve, then B wins `points_b` on p3's serve, from 0-0-2."""
    marks = ["p1 R"]
    for _ in range(points_a):
        marks.append(f"p1 {'L' if marks[-1].endswith('R') else 'R'}")
    # A loses with the only server: side-out to p3 on the right.
    marks.append("p3 R")
    for _ in range(points_b):
        marks.append(f"p3 {'L' if marks[-1].endswith('R') else 'R'}")
    return marks


def test_stopping_short_of_the_target_is_a_game_end_mismatch():
    # A scores 9, side-out, B serves and the players stop after B's tenth rally.
    game = replay_game(serves(*game_to(9, 0)), finished=True, target=11)
    assert game.final_score == (9, 1)
    assert game.rallies[-1].deviations == ("game_end_mismatch",)


def test_a_game_that_ends_at_the_target_fits():
    game = replay_game(serves(*game_to(10, 0)[:-1]), finished=True, target=11)
    assert game.final_score == (11, 0)
    assert game.winner_team == "A"
    assert game.rallies[-1].fits


def test_playing_on_past_the_end_is_a_game_end_mismatch():
    game = replay_game(serves(*game_to(11, 0)), finished=False, target=11)
    assert game.final_score == (11, 0)
    assert game.rallies[-1].deviations == ("game_end_mismatch",)


def test_win_by_two():
    game = replay_game(serves(*game_to(10, 0)[:-1]), finished=True, target=15)
    assert game.rallies[-1].deviations == ("game_end_mismatch",)


def test_no_serves():
    game = replay_game([], finished=False)
    assert game.rallies == ()
    assert game.final_score == (0, 0)


def test_serves_must_be_in_time_order():
    marks = serves("p1 R", "p1 L")
    with pytest.raises(ValueError, match="time order"):
        replay_game(marks[::-1], finished=False)


def test_a_replay_has_no_winner():
    with pytest.raises(ValueError, match="replay"):
        ServeMark(t=1.0, server="p1", side="right", replay=True, winner="A")
