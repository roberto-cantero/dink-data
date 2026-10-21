"""patch.json: corrections on top of a run's events.json, never overwrites."""

import json

import pytest
from pydantic import ValidationError

from dinkdata.contracts.common import dump, load
from dinkdata.contracts.game_log import EventLog
from dinkdata.contracts.patch import Patch, apply_patch
from tests.contracts.examples import example


def events() -> EventLog:
    return EventLog.model_validate(example("events"))


def patch(change=None) -> Patch:
    data = example("patch")
    if change:
        change(data)
    return Patch.model_validate(data)


def test_example_round_trips(tmp_path):
    dump(patch(), tmp_path / "patch.json")
    assert json.loads((tmp_path / "patch.json").read_text()) == example("patch")
    assert load(Patch, tmp_path / "patch.json") == patch()


def test_apply_makes_the_corrected_log_and_leaves_the_original():
    original = events()
    patched = apply_patch(original, patch())
    rally_1, rally_2 = patched.games[0].rallies
    assert [e.id for e in rally_1.events] == ["e1", "e2", "e3", "e4", "e10"]
    assert rally_1.events[1].close_call is True  # type: ignore[union-attr]
    assert [e.id for e in rally_2.events] == ["e5", "e6", "e7", "e8"]
    assert original == events()


def test_an_added_event_lands_in_time_order():
    def early(d):
        d["ops"][1]["value"].update(frame=5540, t=185.13)

    ids = [e.id for e in apply_patch(events(), patch(early)).games[0].rallies[0].events]
    assert ids == ["e1", "e10", "e2", "e3", "e4"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(lambda d: d["ops"][0]["old"].update(close_call=True), "no longer", id="stale"),
        pytest.param(lambda d: d["ops"][2]["old"].update(conf=0.5), "changed", id="stale delete"),
        pytest.param(lambda d: d["ops"][0].update(id="e99"), "no such", id="missing target"),
        pytest.param(
            lambda d: (d["ops"][1].update(id="e2"), d["ops"][1]["value"].update(id="e2")),
            "exists",
            id="dup add",
        ),
        pytest.param(lambda d: d["ops"][1].update(parent="g1_r9"), "no rally", id="no parent"),
        pytest.param(lambda d: d.update(video_id="v_5eed00000000e002"), "patch is for", id="video"),
    ],
)
def test_apply_refuses_a_patch_that_does_not_fit(change, message):
    data = example("patch")
    change(data)
    with pytest.raises(ValueError, match=message):
        apply_patch(events(), Patch.model_validate(data))


def test_apply_validates_the_result():
    def outside(d):
        d["ops"][1]["value"].update(frame=6000, t=200.47)

    with pytest.raises(ValidationError, match="inside"):
        apply_patch(events(), patch(outside))


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda d: d["ops"].reverse(), id="ops out of order"),
        pytest.param(lambda d: d["ops"][0].update(author="Robby Smith"), id="name as author"),
        pytest.param(lambda d: d["ops"][0].update(at="2026-10-21T18:02:11"), id="naive time"),
        pytest.param(lambda d: d["ops"][0]["old"].update(conf=0.9), id="set and old differ"),
        pytest.param(lambda d: d["ops"][0].update(set={}, old={}), id="empty change"),
        pytest.param(
            lambda d: d["ops"][0].update(set={"id": "e3"}, old={"id": "e2"}), id="change id"
        ),
        pytest.param(lambda d: d["ops"][1].update(parent=None), id="event without parent"),
        pytest.param(lambda d: d["ops"][1]["value"].update(id="e11"), id="value id differs"),
        pytest.param(lambda d: d["ops"][0].update(op="move"), id="unknown op"),
        pytest.param(lambda d: d["ops"][0].update(target="player"), id="unknown target"),
    ],
)
def test_rejects(change):
    data = example("patch")
    change(data)
    with pytest.raises(ValidationError):
        Patch.model_validate(data)
