"""stats.json: one entry per game, player and stat."""

import json

import pytest
from pydantic import ValidationError

from dinkdata.contracts.common import dump, load
from dinkdata.contracts.game_log import EventLog
from dinkdata.contracts.stats import Depth, LandingMap, Stats, check_stats
from tests.contracts.examples import example


def stat(data: dict, name: str, subject: str) -> dict:
    return next(s for s in data["stats"] if s["stat"] == name and s["subject"] == subject)


def test_example_round_trips(tmp_path):
    stats = Stats.model_validate(example("stats"))
    dump(stats, tmp_path / "stats.json")
    assert json.loads((tmp_path / "stats.json").read_text()) == example("stats")
    assert load(Stats, tmp_path / "stats.json") == stats


def test_values_keep_their_kind():
    stats = Stats.model_validate(example("stats"))
    values = {(s.stat, s.subject): s.value for s in stats.stats}
    assert values[("net_errors", "p3")] == 2
    assert isinstance(values[("serve_depth", "p1")], Depth)
    assert isinstance(values[("landing_map", "p1")], LandingMap)
    assert '"return":[]' in stats.model_dump_json(by_alias=True)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(
            lambda d: stat(d, "net_errors", "p3").update(subject="A"), "subject", id="team subject"
        ),
        pytest.param(
            lambda d: stat(d, "net_errors", "p3").update(stat="final_score"), "stat", id="score"
        ),
        pytest.param(
            lambda d: stat(d, "net_errors", "p3").update(stat="rallies_won"),
            "stat",
            id="rallies won",
        ),
        pytest.param(lambda d: stat(d, "net_errors", "p3").update(game=None), "game", id="no game"),
        pytest.param(
            lambda d: stat(d, "net_errors", "p3").update(reason="x"), "reason", id="shipped reason"
        ),
        pytest.param(
            lambda d: stat(d, "return_depth", "p4").update(reason=None), "reason", id="no reason"
        ),
        pytest.param(
            lambda d: stat(d, "net_errors", "p3").update(value=None), "value", id="shipped no value"
        ),
        pytest.param(
            lambda d: stat(d, "serve_in_pct", "p1").update(value=0.5), "num / den", id="ratio"
        ),
        pytest.param(
            lambda d: stat(d, "serve_in_pct", "p1").update(num=None), "num and den", id="no num"
        ),
        pytest.param(
            lambda d: stat(d, "net_errors", "p3").update(num=1, den=2), "num and den", id="count"
        ),
        pytest.param(
            lambda d: stat(d, "serve_in_pct", "p1").update(value=1.0, num=9, den=8),
            "exceed",
            id="num > den",
        ),
        pytest.param(
            lambda d: stat(d, "net_errors", "p3").update(value=1.5), "kind", id="fraction count"
        ),
        pytest.param(
            lambda d: stat(d, "serve_depth", "p1").update(value=3), "kind", id="depth as count"
        ),
        pytest.param(
            lambda d: d["stats"].append(dict(stat(d, "net_errors", "p3"))), "one entry", id="dup"
        ),
        pytest.param(
            lambda d: stat(d, "net_errors", "p3").update(stat="dinks"), "stat", id="unknown stat"
        ),
    ],
)
def test_rejects(change, message):
    data = example("stats")
    change(data)
    with pytest.raises(ValidationError, match=message):
        Stats.model_validate(data)


def test_stats_match_their_game_log():
    log = EventLog.model_validate(example("events"))
    assert check_stats(Stats.model_validate(example("stats")), log) == []
    data = example("stats")
    stat(data, "net_errors", "p3").update(game="g2")
    assert any("g2" in e for e in check_stats(Stats.model_validate(data), log))
    data["video_id"] = "v_5eed00000000e002"
    assert check_stats(Stats.model_validate(data), log)
