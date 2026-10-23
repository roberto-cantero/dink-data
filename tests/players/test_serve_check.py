"""The partner-identity check at the serve: finding the server, the team halves and the score."""

import pytest

from dinkdata.players.serve_check import (
    ServeResult,
    nearest_two,
    on_court,
    serving_half,
    split_server,
    summarise,
    team_a_half,
    wilson,
)


def test_on_court_keeps_generous_margins_behind_the_baselines():
    assert on_court(10, 22)
    assert on_court(-2, 50)
    assert on_court(21, -12)
    assert not on_court(-8, 22)
    assert not on_court(10, 64)


def test_nearest_two_drops_whoever_stands_furthest_outside_the_lines():
    """A spectator behind the baseline loses to two players, one of them just outside."""
    points = [(5.0, -14.0), (3.0, 2.0), (15.0, -3.0)]
    assert nearest_two(points) == [1, 2]
    assert nearest_two(points[:2]) == [0, 1]


def test_the_near_server_on_the_right_is_on_the_image_right():
    """The near team faces away from the camera, so its right is larger x."""
    assert split_server([4.0, 15.0], "near", "right") == (1, 0)
    assert split_server([4.0, 15.0], "near", "left") == (0, 1)


def test_the_far_server_on_the_right_is_on_the_image_left():
    """The far team faces the camera, so its right is smaller x."""
    assert split_server([4.0, 15.0], "far", "right") == (0, 1)
    assert split_server([4.0, 15.0], "far", "left") == (1, 0)


def test_the_serving_half_has_nobody_up_at_the_kitchen():
    """The receiver's partner waits at the kitchen line, the serving team stays back."""
    near = [(5.0, 43.0), (15.0, 42.0)]
    far = [(15.0, 1.0), (5.0, 15.5)]
    assert serving_half(near, far) == "near"
    assert serving_half(far=[(15.0, 1.0), (5.0, 2.0)], near=[(5.0, 30.0), (15.0, 43.0)]) == "far"


def test_serving_half_needs_both_halves():
    assert serving_half([], [(15.0, 1.0)]) is None


def test_team_a_half_follows_the_majority_of_serves():
    votes = [("A", "near"), ("B", "far"), ("A", "near"), ("B", "near")]
    assert team_a_half(votes) == ("near", 0.75)
    assert team_a_half([]) == (None, 0.0)


def test_wilson_interval():
    lo, hi = wilson(8, 10)
    assert lo == pytest.approx(0.490, abs=1e-3)
    assert hi == pytest.approx(0.943, abs=1e-3)
    assert wilson(0, 0) == (0.0, 1.0)


def result(half, gold, predicted, method="colour"):
    return ServeResult(
        video_id="v_0000000000000000",
        rally_id="g1_r2",
        t=1.0,
        half=half,
        method=method,
        gold=gold,
        predicted=predicted,
        margin=0.1,
    )


def test_summary_splits_near_and_far_and_counts_missed_servers():
    rows = summarise(
        [
            result("near", "p1", "p1"),
            result("near", "p1", "p2"),
            result("near", "p3", None),
            result("far", "p4", "p4"),
        ]
    )
    near = next(r for r in rows if r.half == "near")
    assert (near.serves, near.found, near.correct) == (3, 2, 1)
    assert near.accuracy == pytest.approx(0.5)
    far = next(r for r in rows if r.half == "far")
    assert (far.serves, far.found, far.correct) == (1, 1, 1)
    both = next(r for r in rows if r.half == "both")
    assert (both.serves, both.found, both.correct) == (4, 3, 2)
