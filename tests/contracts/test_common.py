from fractions import Fraction

import pytest

from dinkdata.contracts.common import parse_score_call, t_from_pts, team_of


def test_t_counts_seconds_from_the_first_frame():
    assert t_from_pts(9000, first_pts=0, time_base=Fraction(1, 90000)) == pytest.approx(0.1)


def test_t_ignores_a_stream_that_starts_late():
    # MPEG-TS streams often start at a non-zero PTS. t still starts at 0 on the first frame.
    assert t_from_pts(126000, first_pts=126000, time_base=Fraction(1, 90000)) == 0.0
    assert t_from_pts(216000, first_pts=126000, time_base=Fraction(1, 90000)) == 1.0


def test_t_before_the_first_frame_is_an_error():
    with pytest.raises(ValueError, match="before the first frame"):
        t_from_pts(10, first_pts=20, time_base=Fraction(1, 1000))


def test_teams_follow_the_id_convention():
    assert [team_of(p) for p in ("p1", "p2", "p3", "p4")] == ["A", "A", "B", "B"]


def test_parse_score_call():
    assert parse_score_call("4-3-2") == (4, 3, 2)
    assert parse_score_call("10-11-1") == (10, 11, 1)


@pytest.mark.parametrize("call", ["4-3", "4-3-3", "a-b-c", "4-3-1-", " 4-3-1"])
def test_parse_score_call_rejects(call):
    with pytest.raises(ValueError):
        parse_score_call(call)
