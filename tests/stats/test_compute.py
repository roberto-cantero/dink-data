"""The v1 stats, one rule at a time, from hand-written game logs (docs/STATS.md).

In these logs team A (p1, p2) stands at the near end and team B (p3, p4) at the far end, so a
serve by p1 from the right lands in the far box, 0 <= x <= 10 and 0 <= y < 15.
"""

from typing import get_args

import pytest

from dinkdata.contracts.stats import Depth, LandingMap, StatName, Stats, check_stats
from dinkdata.stats.compute import SHIP_THRESHOLD, compute_stats
from tests.stats.logs import bounce, game_log, hit, net, rally, stat, unseen_bounce

RUN = "test-run"

# A clean rally: p1 serves in, p3 returns in, p1 hits a winner that bounces twice on B's side.
CLEAN = rally(
    hit("p1", 1),
    bounce(5, 8),
    hit("p3", 2),
    bounce(12, 38),
    hit("p1", 3),
    bounce(14, 6),
    bounce(14, 2),
    end="double_bounce",
)


def run(*rallies: dict) -> Stats:
    return compute_stats(game_log(list(rallies)), RUN)


# Serve in %


def test_serve_in_pct_counts_serves_whose_first_bounce_is_in_the_diagonal_court():
    stats = run(
        rally(hit("p1", 1), bounce(5, 8), hit("p3", 2), bounce(10, 30)),
        rally(hit("p1", 1), bounce(15, 8), end="out", winner="B"),
    )
    s = stat(stats, "serve_in_pct", "p1")
    assert (s.value, s.num, s.den, s.shipped) == (0.5, 1, 2, True)


def test_serve_from_the_far_end_lands_in_the_near_box():
    stats = run(rally(hit("p3", 1), bounce(15, 36), server="p3", receiver="p1", winner="B"))
    s = stat(stats, "serve_in_pct", "p3")
    assert (s.num, s.den) == (1, 1)


def test_serve_on_the_kitchen_line_is_a_fault():
    stats = run(rally(hit("p1", 1), bounce(5, 15), end="out", winner="B"))
    s = stat(stats, "serve_in_pct", "p1")
    assert (s.num, s.den) == (0, 1)


def test_serve_on_any_other_line_of_its_service_court_is_in():
    stats = run(
        rally(hit("p1", 1), bounce(10, 8)),
        rally(hit("p1", 1), bounce(0, 8)),
        rally(hit("p1", 1), bounce(5, 0)),
    )
    s = stat(stats, "serve_in_pct", "p1")
    assert (s.num, s.den) == (3, 3)


def test_serve_whose_first_bounce_isnt_visible_is_left_out():
    stats = run(
        rally(hit("p1", 1), bounce(5, 8)),
        rally(hit("p1", 1), unseen_bounce()),
    )
    s = stat(stats, "serve_in_pct", "p1")
    assert (s.num, s.den) == (1, 1)
    depth = stat(stats, "serve_depth", "p1").value
    assert isinstance(depth, Depth)
    assert depth.deep + depth.medium + depth.short == 1


def test_net_cord_serve_that_lands_in_is_in():
    stats = run(rally(hit("p1", 1), net(), bounce(5, 12)))
    s = stat(stats, "serve_in_pct", "p1")
    assert (s.num, s.den) == (1, 1)


def test_serve_into_the_net_counts_as_not_in():
    stats = run(rally(hit("p1", 1), net(), end="net", winner="B"))
    s = stat(stats, "serve_in_pct", "p1")
    assert (s.num, s.den) == (0, 1)


def test_serve_volleyed_by_the_receiver_isnt_judged():
    stats = run(rally(hit("p1", 1), hit("p3", 2, volley=True), end="fault", winner="A"))
    s = stat(stats, "serve_in_pct", "p1")
    assert s.den == 0
    assert s.reason == "no_serves"


def test_close_call_is_left_out_until_reviewed():
    close = (hit("p1", 1), bounce(5, 14.9, close_call=True))
    unreviewed = run(rally(*close), rally(hit("p1", 1), bounce(5, 8)))
    assert stat(unreviewed, "serve_in_pct", "p1").den == 1
    reviewed = run(rally(*close, reviewed=True), rally(hit("p1", 1), bounce(5, 8)))
    assert stat(reviewed, "serve_in_pct", "p1").den == 2


# Serve depth


def test_serve_depth_buckets_feet_to_the_receivers_baseline():
    stats = run(
        rally(hit("p1", 1), bounce(5, 4)),
        rally(hit("p1", 1), bounce(5, 5)),
        rally(hit("p1", 1), bounce(5, 8)),
        rally(hit("p1", 1), bounce(5, 10)),
        rally(hit("p1", 1), bounce(5, 12)),
        rally(hit("p3", 1), bounce(15, 40), server="p3", receiver="p1", winner="B"),
    )
    assert stat(stats, "serve_depth", "p1").value == Depth(deep=2, medium=2, short=1)
    assert stat(stats, "serve_depth", "p3").value == Depth(deep=1, medium=0, short=0)


def test_serve_depth_counts_only_serves_that_landed_in():
    stats = run(
        rally(hit("p1", 1), bounce(5, 4)),
        rally(hit("p1", 1), bounce(5, -2), end="out", winner="B"),
    )
    assert stat(stats, "serve_depth", "p1").value == Depth(deep=1, medium=0, short=0)


def test_serve_depth_with_no_serve_in_doesnt_ship():
    stats = run(rally(hit("p1", 1), bounce(5, -2), end="out", winner="B"))
    s = stat(stats, "serve_depth", "p1")
    assert (s.value, s.shipped, s.reason) == (None, False, "no_serves_in")


# Return in %


def test_return_in_pct_counts_returns_whose_first_bounce_is_in_the_servers_half():
    stats = run(
        rally(hit("p1", 1), bounce(5, 8), hit("p3", 2), bounce(10, 40)),
        rally(hit("p1", 1), bounce(5, 8), hit("p3", 2), bounce(10, 46), end="out"),
        rally(hit("p1", 1), bounce(5, 8), hit("p3", 2), bounce(21, 30), end="out"),
    )
    s = stat(stats, "return_in_pct", "p3")
    assert (s.num, s.den) == (1, 3)


def test_return_that_doesnt_cross_the_net_isnt_in():
    stats = run(
        rally(hit("p1", 1), bounce(5, 8), hit("p3", 2), net(), end="net"),
        rally(hit("p1", 1), bounce(5, 8), hit("p3", 2), bounce(10, 18)),
    )
    s = stat(stats, "return_in_pct", "p3")
    assert (s.num, s.den) == (0, 2)


def test_return_hit_before_the_serve_bounced_is_a_fault():
    stats = run(rally(hit("p1", 1), hit("p3", 2, volley=True), bounce(10, 40), end="fault"))
    s = stat(stats, "return_in_pct", "p3")
    assert (s.num, s.den) == (0, 1)


def test_third_shot_hit_before_the_return_bounced_is_a_fault():
    stats = run(
        rally(
            hit("p1", 1),
            bounce(5, 8),
            hit("p3", 2),
            hit("p2", 3, volley=True),
            end="fault",
            winner="B",
        )
    )
    # The return was never judged, the fault is no net or out error, and nobody hit a winner.
    assert stat(stats, "return_in_pct", "p3").den == 0
    for player in ["p1", "p2", "p3", "p4"]:
        for name in ["net_errors", "out_errors", "winners"]:
            assert stat(stats, name, player).value == 0


def test_returner_falls_back_to_the_serves_receiver():
    stats = run(rally(hit("p1", 1), bounce(5, 8), hit(None, 2), bounce(10, 40), receiver="p4"))
    assert stat(stats, "return_in_pct", "p4").den == 1


def test_return_depth_buckets_feet_to_the_servers_baseline():
    stats = run(
        rally(hit("p1", 1), bounce(5, 8), hit("p3", 2), bounce(10, 41)),
        rally(hit("p1", 1), bounce(5, 8), hit("p3", 2), bounce(10, 30)),
    )
    assert stat(stats, "return_depth", "p3").value == Depth(deep=1, medium=0, short=1)


# Net errors, out errors and serve faults


def test_net_error_belongs_to_the_shot_that_ended_the_rally():
    stats = run(
        rally(
            hit("p1", 1),
            bounce(5, 8),
            hit("p3", 2),
            bounce(10, 40),
            hit("p2", 3),
            bounce(8, 10),
            hit("p4", 4),
            net(),
            end="net",
        )
    )
    assert stat(stats, "net_errors", "p4").value == 1
    for player in ["p1", "p2", "p3"]:
        assert stat(stats, "net_errors", player).value == 0


def test_out_error_counts_the_rally_ending_shot_that_bounced_out():
    stats = run(
        rally(
            hit("p1", 1),
            bounce(5, 8),
            hit("p3", 2),
            bounce(10, 40),
            hit("p2", 3),
            bounce(21, 4),
            end="out",
            winner="B",
        )
    )
    assert stat(stats, "out_errors", "p2").value == 1
    assert stat(stats, "out_errors", "p3").value == 0


def test_serve_faults_are_counted_apart_from_net_and_out_errors():
    stats = run(
        rally(hit("p1", 1), net(), end="net", winner="B"),
        rally(hit("p1", 1), bounce(5, -3), end="out", winner="B"),
    )
    assert stat(stats, "serve_faults", "p1").value == 2
    assert stat(stats, "net_errors", "p1").value == 0
    assert stat(stats, "out_errors", "p1").value == 0


def test_error_by_an_unknown_hitter_lowers_the_losing_teams_confidence():
    stats = run(
        CLEAN,
        rally(hit("p1", 1), bounce(5, 8), hit(None, 2), net(), end="net", winner="A"),
    )
    s = stat(stats, "net_errors", "p3")
    assert s.value == 0
    assert s.conf == 0
    assert (s.shipped, s.reason) == (False, "low_attribution_conf")
    assert stat(stats, "net_errors", "p1").shipped


def test_out_error_on_an_unreviewed_close_call_is_left_out():
    stats = run(
        rally(
            hit("p1", 1),
            bounce(5, 8),
            hit("p3", 2),
            bounce(20.05, 40, close_call=True),
            end="out",
        )
    )
    s = stat(stats, "out_errors", "p3")
    assert s.value == 0
    assert s.reason == "close_call_review"


# Winners


def test_winner_when_the_ball_bounced_twice_on_the_opponents_side():
    stats = run(CLEAN)
    assert stat(stats, "winners", "p1").value == 1
    assert stat(stats, "winners", "p3").value == 0


def test_winner_when_the_ball_hit_an_opponent():
    stats = run(
        rally(hit("p1", 1), bounce(5, 8), hit("p3", 2), bounce(10, 40), hit("p2", 3), end="fault")
    )
    assert stat(stats, "winners", "p2").value == 1


def test_winner_when_the_second_bounce_went_out_of_frame():
    # The ball bounced in on B's half, then left the picture. Nothing came after it.
    stats = run(
        rally(hit("p1", 1), bounce(5, 8), hit("p3", 2), bounce(10, 40), hit("p1", 3), bounce(4, 6))
    )
    assert stat(stats, "winners", "p1").value == 1


def test_no_winner_when_the_last_bounce_was_on_the_hitters_own_half_or_out():
    stats = run(
        rally(
            hit("p1", 1), bounce(5, 8), hit("p3", 2), bounce(10, 40), hit("p1", 3), bounce(4, 30)
        ),
        rally(
            hit("p1", 1), bounce(5, 8), hit("p3", 2), bounce(10, 40), hit("p1", 3), bounce(4, -1)
        ),
    )
    assert stat(stats, "winners", "p1").value == 0


def test_no_winner_when_an_opponent_touched_the_ball():
    stats = run(
        rally(
            hit("p1", 1),
            bounce(5, 8),
            hit("p3", 2),
            bounce(10, 40),
            hit("p1", 3),
            bounce(4, 6),
            end="unreturned",
        )
    )
    assert stat(stats, "winners", "p1").value == 0


def test_no_winner_for_the_losing_teams_last_shot():
    stats = run(rally(hit("p1", 1), bounce(5, 8), hit("p3", 2), bounce(10, 40), end="unexplained"))
    assert stat(stats, "winners", "p3").value == 0


def test_unknown_end_with_an_unseen_bounce_is_left_out_of_winners():
    stats = run(
        CLEAN,
        rally(
            hit("p1", 1), bounce(5, 8), hit("p3", 2), bounce(10, 40), hit("p1", 3), unseen_bounce()
        ),
    )
    s = stat(stats, "winners", "p1")
    assert s.value == 1
    assert s.conf == pytest.approx(0.9 * 1 / 2)
    assert (s.shipped, s.reason) == (False, "bounces_not_visible")


# Landing map


def test_landing_map_holds_serve_return_and_out_error_bounces():
    stats = run(
        rally(
            hit("p1", 1),
            bounce(5, 8),
            hit("p3", 2),
            bounce(10, 40),
            hit("p1", 3),
            bounce(21, 4),
            end="out",
            winner="B",
        ),
        rally(hit("p1", 1), unseen_bounce()),
    )
    p1 = stat(stats, "landing_map", "p1").value
    assert p1 == LandingMap.model_validate(
        {"serve": [(5, 8)], "return": [], "out_error": [(21, 4)]}
    )
    p3 = stat(stats, "landing_map", "p3").value
    assert p3 == LandingMap.model_validate({"serve": [], "return": [(10, 40)], "out_error": []})


def test_landing_map_with_no_bounces_doesnt_ship():
    s = stat(run(CLEAN), "landing_map", "p2")
    assert (s.shipped, s.reason) == (False, "no_bounces")


# Edge cases across stats


def test_rally_that_broke_the_serving_rules_still_counts():
    # p1 serves twice from the right after losing the first rally, which the rules forbid.
    stats = run(
        rally(hit("p1", 1), bounce(5, 8), hit("p3", 2), bounce(10, 40), winner="B"),
        rally(hit("p1", 1), bounce(5, 8), hit("p3", 2), bounce(10, 40), winner="B"),
    )
    assert stat(stats, "serve_in_pct", "p1").den == 2
    assert stat(stats, "return_in_pct", "p3").den == 2


def test_replayed_rally_counts_toward_no_stat():
    replayed = rally(
        hit("p1", 1), bounce(5, 8), hit("p3", 2), net(), end="net", replay=True, conf=0.2
    )
    with_replay = run(CLEAN, replayed)
    without = run(CLEAN)
    assert [s.model_dump() for s in with_replay.stats] == [s.model_dump() for s in without.stats]


def test_no_stat_reports_the_score():
    stats = run(CLEAN)
    names = {s.stat for s in stats.stats}
    assert names == set(get_args(StatName))
    assert {s.subject for s in stats.stats} == {"p1", "p2", "p3", "p4"}


# Confidence and shipping


def test_every_player_gets_every_stat_in_every_game():
    log = game_log([CLEAN], [CLEAN, CLEAN])
    stats = compute_stats(log, RUN)
    assert len(stats.stats) == 2 * 4 * len(get_args(StatName))
    assert check_stats(stats, log) == []
    assert stats.video_id == log.video.id
    assert stats.run_id == RUN


def test_confidence_is_the_mean_weakest_link_times_the_share_judged():
    stats = run(
        rally(hit("p1", 1, conf=0.8), bounce(5, 8, conf=0.7)),
        rally(hit("p1", 1), bounce(5, 8), conf=0.6),
        rally(hit("p1", 1), unseen_bounce()),
    )
    s = stat(stats, "serve_in_pct", "p1")
    assert s.conf == pytest.approx((0.7 + 0.6) / 2 * 2 / 3, abs=1e-3)


def test_a_count_of_zero_takes_the_games_mean_rally_confidence():
    stats = run(CLEAN, CLEAN | {"conf": 0.7})
    s = stat(stats, "net_errors", "p2")
    assert s.value == 0
    assert s.conf == pytest.approx(0.8)
    assert s.shipped


def test_low_confidence_stat_doesnt_ship():
    stats = run(rally(hit("p1", 1, conf=0.3), bounce(5, 8)))
    s = stat(stats, "serve_in_pct", "p1")
    assert s.conf < SHIP_THRESHOLD["serve_in_pct"]
    assert (s.shipped, s.reason, s.value) == (False, "low_conf", 1.0)


def test_player_with_no_serves_or_returns():
    stats = run(CLEAN)
    assert stat(stats, "serve_in_pct", "p2").reason == "no_serves"
    assert stat(stats, "return_in_pct", "p4").reason == "no_returns"
    assert stat(stats, "serve_in_pct", "p2").value is None


def test_serves_whose_bounces_are_all_unseen():
    stats = run(rally(hit("p1", 1), unseen_bounce()), rally(hit("p1", 1), unseen_bounce()))
    s = stat(stats, "serve_in_pct", "p1")
    assert (s.den, s.shipped, s.reason) == (0, False, "bounces_not_visible")


def test_rally_without_events_is_left_out():
    stats = run(CLEAN, rally())
    s = stat(stats, "serve_in_pct", "p1")
    assert (s.den, s.reason) == (1, "events_missing")


def test_game_with_only_replays_has_no_rallies():
    stats = run(rally(hit("p1", 1), bounce(5, 8), replay=True))
    for s in stats.stats:
        assert (s.shipped, s.reason, s.conf) == (False, "no_rallies", 0)


def test_compute_stats_is_pure():
    log = game_log([CLEAN, rally(hit("p1", 1), unseen_bounce())])
    before = log.model_dump()
    first = compute_stats(log, RUN)
    assert log.model_dump() == before
    assert compute_stats(log, RUN) == first


# Rare gaps in the log


def test_return_by_an_unknown_player_is_left_out_for_the_receiving_team():
    stats = run(
        CLEAN,
        rally(hit("p1", 1), bounce(5, 8), hit(None, 2), bounce(10, 40), receiver=None),
    )
    s = stat(stats, "return_in_pct", "p4")
    assert (s.den, s.reason) == (0, "low_attribution_conf")
    assert stat(stats, "return_in_pct", "p3").reason == "low_attribution_conf"


def test_error_in_a_rally_without_events_is_left_out_for_the_losers():
    stats = run(CLEAN, rally(end="net", winner="A"))
    s = stat(stats, "net_errors", "p3")
    assert (s.value, s.reason) == (0, "events_missing")
    assert stat(stats, "net_errors", "p1").shipped


def test_unknown_winner_is_left_out_of_the_last_hitters_winners():
    stats = run(CLEAN, CLEAN | {"winner_team": None, "winner_source": None})
    s = stat(stats, "winners", "p1")
    assert (s.value, s.reason) == (1, "winner_unknown")
    assert stat(stats, "winners", "p2").shipped


def test_out_of_frame_winner_finds_the_halves_from_the_return_when_the_serve_wasnt_seen():
    seen_return = rally(
        hit("p1", 1), unseen_bounce(), hit("p3", 2), bounce(10, 40), hit("p1", 3), bounce(4, 6)
    )
    assert stat(run(seen_return), "winners", "p1").value == 1
    nothing_seen = rally(
        hit("p1", 1), unseen_bounce(), hit("p3", 2), unseen_bounce(), hit("p1", 3), bounce(4, 6)
    )
    s = stat(run(CLEAN, nothing_seen), "winners", "p1")
    assert (s.value, s.reason) == (1, "bounces_not_visible")
