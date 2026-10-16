"""events.schema.json: the rules it enforces, plus the cross-reference rules from its $comment."""

import copy
import json
from pathlib import Path

import jsonschema
import pytest

CONTRACTS = Path(__file__).parents[2] / "contracts"
SCHEMA = json.loads((CONTRACTS / "events.schema.json").read_text())
EXAMPLE = json.loads((CONTRACTS / "events.example.json").read_text())


def cross_reference_errors(log: dict) -> list[str]:
    """Rules from the schema's $comment that JSON Schema can't express."""
    errors = []
    player_ids = [p["id"] for p in log["players"]]
    if len(set(player_ids)) != len(player_ids):
        errors.append("duplicate player id")
    ids = [r["id"] for r in log["rallies"]] + [e["id"] for r in log["rallies"] for e in r["events"]]
    if len(set(ids)) != len(ids):
        errors.append("duplicate rally or event id")
    previous_end = -1
    for rally in log["rallies"]:
        if rally["start_frame"] <= previous_end:
            errors.append(f"{rally['id']}: overlaps or is out of order")
        previous_end = rally["end_frame"]
        if rally["server"] not in player_ids:
            errors.append(f"{rally['id']}: unknown server")
        times = [e["t"] for e in rally["events"]]
        if times != sorted(times):
            errors.append(f"{rally['id']}: events not sorted by t")
        if any(not rally["start_frame"] <= t <= rally["end_frame"] for t in times):
            errors.append(f"{rally['id']}: event outside the rally")
        for event in rally["events"]:
            if event["type"] == "hit" and event["player"] not in [*player_ids, None]:
                errors.append(f"{event['id']}: unknown player")
    return errors


def is_valid(log: dict) -> bool:
    return jsonschema.Draft202012Validator(SCHEMA).is_valid(log)


def test_example_follows_cross_reference_rules():
    assert cross_reference_errors(EXAMPLE) == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda log: log["rallies"][0]["events"].reverse(), "events not sorted by t"),
        (lambda log: log["rallies"][0].update(server="p9"), "unknown server"),
        (lambda log: log["rallies"][1].update(start_frame=200), "overlaps or is out of order"),
        (
            lambda log: log["rallies"][1]["events"][0].update(id="r1_e1"),
            "duplicate rally or event id",
        ),
    ],
)
def test_cross_reference_rules_catch_mistakes(change, expected):
    log = copy.deepcopy(EXAMPLE)
    change(log)
    assert any(expected in error for error in cross_reference_errors(log))


def first_hit(log: dict) -> dict:
    return log["rallies"][0]["events"][0]


def first_bounce(log: dict) -> dict:
    return log["rallies"][0]["events"][1]


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda log: log.update(schema="dinkdata.events/v2"), id="wrong version"),
        pytest.param(lambda log: log["court"].update(units="m"), id="units not feet"),
        pytest.param(
            lambda log: log["players"].append({**log["players"][0], "id": "p5"}), id="5 players"
        ),
        pytest.param(lambda log: log["players"][0].update(team="C"), id="unknown team"),
        pytest.param(lambda log: log["rallies"][0].update(score_before="4-3-3"), id="bad score"),
        pytest.param(
            lambda log: log["rallies"][0].update(end_reason="let"), id="unknown end reason"
        ),
        pytest.param(lambda log: first_hit(log).update(conf=1.2), id="conf above 1"),
        pytest.param(lambda log: first_hit(log).update(shot="smash"), id="unknown shot"),
        pytest.param(lambda log: first_hit(log).pop("volley"), id="hit missing volley"),
        pytest.param(
            lambda log: first_hit(log).update(court_xy=[1, 2]), id="hit with bounce field"
        ),
        pytest.param(lambda log: first_bounce(log).update(court_xy=[1, 2, 3]), id="3d bounce"),
        pytest.param(lambda log: first_bounce(log).update(t=-1), id="negative frame"),
        pytest.param(lambda log: log["rallies"][0].update(typo=True), id="unknown rally field"),
    ],
)
def test_schema_rejects(change):
    log = copy.deepcopy(EXAMPLE)
    change(log)
    assert not is_valid(log)


def test_unknown_winner_reason_shot_and_player_are_allowed():
    log = copy.deepcopy(EXAMPLE)
    log["rallies"][0].update(winner_team=None, end_reason=None)
    first_hit(log).update(player=None, shot=None)
    assert is_valid(log)
