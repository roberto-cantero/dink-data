"""events.json: the game log. Marti owns games, rallies and serves; Robby owns the event list."""

import json

import pytest
from pydantic import ValidationError

from dinkdata.contracts.common import dump, load
from dinkdata.contracts.game_log import EventLog
from tests.contracts.examples import example


def rally(log: dict, n: int) -> dict:
    return log["games"][0]["rallies"][n - 1]


def event(log: dict, rally_n: int, n: int) -> dict:
    return rally(log, rally_n)["events"][n - 1]


def test_example_round_trips(tmp_path):
    log = EventLog.model_validate(example("events"))
    dump(log, tmp_path / "events.json")
    assert json.loads((tmp_path / "events.json").read_text()) == example("events")
    assert load(EventLog, tmp_path / "events.json") == log


def test_bounce_in_keeps_its_json_name():
    log = EventLog.model_validate(example("events"))
    bounce = log.games[0].rallies[0].events[1]
    assert bounce.type == "bounce"
    assert bounce.in_ is True
    assert '"in":true' in log.model_dump_json(by_alias=True)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(lambda d: d["players"][0].update(team="B"), "team", id="p1 on team B"),
        pytest.param(lambda d: d["players"][1].update(id="p1"), "unique", id="duplicate player"),
        pytest.param(lambda d: d["players"].pop(), "4", id="three players"),
        pytest.param(lambda d: rally(d, 1)["events"].reverse(), "sorted", id="events unsorted"),
        pytest.param(lambda d: event(d, 1, 1).update(t=184.0), "inside", id="event before rally"),
        pytest.param(
            lambda d: event(d, 1, 1).update(frame=5500), "inside", id="event frame outside"
        ),
        pytest.param(lambda d: event(d, 2, 1).update(id="e1"), "unique", id="duplicate event id"),
        pytest.param(lambda d: rally(d, 2).update(score_before="0-0-2"), "score", id="bad score"),
        pytest.param(
            lambda d: rally(d, 2).update(winner_team=None), "winner_source", id="source, no winner"
        ),
        pytest.param(
            lambda d: d["segments"][1].update(start_frame=5000, start_t=166.0),
            "overlap",
            id="segments overlap",
        ),
        pytest.param(
            lambda d: rally(d, 1).update(end_frame=5400), "frame", id="end frame before start"
        ),
    ],
)
def test_rules_across_the_log(change, message):
    log = example("events")
    change(log)
    with pytest.raises(ValidationError, match=message):
        EventLog.model_validate(log)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda d: d.update(schema="dinkdata.events/v0"), id="wrong version"),
        pytest.param(lambda d: d["camera"].update(id="cam-41"), id="raw camera id"),
        pytest.param(lambda d: rally(d, 1).pop("start_frame"), id="pipeline rally needs frames"),
        pytest.param(lambda d: rally(d, 1).update(end_reason="let"), id="unknown end reason"),
        pytest.param(lambda d: rally(d, 1).update(winner_source="vibes"), id="unknown source"),
        pytest.param(lambda d: event(d, 1, 1).update(type="serve"), id="unknown event type"),
        pytest.param(lambda d: event(d, 1, 1).update(court_xy=[1, 2]), id="hit with bounce field"),
        pytest.param(lambda d: event(d, 1, 2).update(court_xy=[1, 2, 3]), id="3d bounce"),
        pytest.param(lambda d: event(d, 1, 2).update(conf=-0.1), id="negative conf"),
        pytest.param(lambda d: d["segments"][0].update(type="lunch"), id="unknown segment type"),
        pytest.param(lambda d: d["games"][0].update(format="rally"), id="rally scoring"),
    ],
)
def test_schema_rejects(change):
    log = example("events")
    change(log)
    with pytest.raises(ValidationError):
        EventLog.model_validate(log)


def test_unknowns_are_allowed():
    log = example("events")
    rally(log, 1).update(winner_team=None, winner_source=None, end_reason=None)
    rally(log, 1)["serve"]["receiver"] = None
    event(log, 1, 1)["player"] = None
    log["players"][0]["crop"] = None
    # With r1's winner unknown, r2's call of 1-0-2 still fits a point for team A.
    EventLog.model_validate(log)
