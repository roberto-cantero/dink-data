"""rallies.json: rally-level gold labels from the browser rally labeller."""

import json
from typing import get_args

import pytest
from pydantic import ValidationError

from dinkdata.contracts.common import dump, load
from dinkdata.contracts.rallies import RallyLabels, RuleDeviation, RuleDeviationType
from tests.contracts.examples import example


def g1(labels: dict) -> dict:
    return labels["games"][0]


def rally(labels: dict, n: int, game: int = 0) -> dict:
    return labels["games"][game]["rallies"][n - 1]


def test_example_round_trips(tmp_path):
    labels = RallyLabels.model_validate(example("rallies"))
    dump(labels, tmp_path / "rallies.json")
    assert json.loads((tmp_path / "rallies.json").read_text()) == example("rallies")
    assert load(RallyLabels, tmp_path / "rallies.json") == labels


def test_example_has_no_frames_because_the_browser_cannot_know_them():
    labels = RallyLabels.model_validate(example("rallies"))
    assert all(r.start_frame is None for g in labels.games for r in g.rallies)


def test_frames_are_allowed_once_snapped():
    labels = example("rallies")
    rally(labels, 1).update(start_frame=3761, end_frame=4067)
    RallyLabels.model_validate(labels)


def test_an_unknown_winner_allows_either_next_score():
    labels = example("rallies")
    rally(labels, 10)["winner_team"] = None  # the next call, 4-1-1, says team A won it
    RallyLabels.model_validate(labels)


@pytest.mark.parametrize("kind", get_args(RuleDeviationType))
def test_every_deviation_type_is_accepted(kind):
    assert RuleDeviation.model_validate({"type": kind, "conf": 1.0}).type == kind


def truncate_g1_to_8_rallies(labels: dict) -> None:
    game = g1(labels)
    game["rallies"] = game["rallies"][:8]
    game["end_t"] = game["rallies"][-1]["end_t"] + 2.0
    game.update(final_score={"A": 2, "B": 1}, winner_team="A")


def test_players_stopping_early_is_a_game_end_mismatch():
    labels = example("rallies")
    truncate_g1_to_8_rallies(labels)
    with pytest.raises(ValidationError, match="target"):
        RallyLabels.model_validate(labels)
    g1(labels)["rallies"][-1]["rule_deviations"] = [{"type": "game_end_mismatch", "conf": 1.0}]
    RallyLabels.model_validate(labels)


def rename_g2_to_g1(labels: dict) -> None:
    labels["games"][1]["id"] = "g1"
    for n, r in enumerate(labels["games"][1]["rallies"], 90):
        r["id"] = f"g1_r{n}"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(lambda d: rally(d, 5).update(score_before="2-1-1"), "score", id="bad score"),
        pytest.param(
            lambda d: rally(d, 1).update(score_before="0-0-1"), "0-0-2", id="first not 0-0-2"
        ),
        pytest.param(
            lambda d: g1(d).update(final_score={"A": 11, "B": 2}), "final", id="bad final score"
        ),
        pytest.param(
            lambda d: rally(d, 4).update(winner_team="B"), "replay", id="replay with a winner"
        ),
        pytest.param(
            lambda d: rally(d, 1)["serve"].update(receiver="p2"), "receiver", id="own receiver"
        ),
        pytest.param(
            lambda d: rally(d, 9)["rule_deviations"].append(
                {"type": "game_end_mismatch", "conf": 1.0}
            ),
            "last rally",
            id="end mismatch mid-game",
        ),
        pytest.param(lambda d: g1(d).update(winner_team=None), "winner", id="finished, no winner"),
        pytest.param(
            lambda d: d["games"][1].update(winner_team="B"), "winner", id="cut off, with winner"
        ),
        pytest.param(lambda d: g1(d).update(winner_team="B"), "winner", id="winner not ahead"),
        pytest.param(lambda d: rally(d, 2).update(start_t=130.0), "overlap", id="rallies overlap"),
        pytest.param(lambda d: rally(d, 1).update(start_t=100.0), "inside", id="outside its game"),
        pytest.param(lambda d: d["games"][1].update(start_t=500.0), "overlap", id="games overlap"),
        pytest.param(lambda d: rally(d, 3).update(end_t=184.0), "end_t", id="ends before start"),
        pytest.param(lambda d: rally(d, 2).update(id="g1_r1"), "unique", id="duplicate rally id"),
        pytest.param(lambda d: rally(d, 1).update(id="g2_r9"), "g1_", id="id from another game"),
        pytest.param(rename_g2_to_g1, "unique", id="duplicate game id"),
        pytest.param(
            lambda d: rally(d, 1).update(start_frame=500, end_frame=400), "frame", id="frames"
        ),
    ],
)
def test_rules_across_rallies(change, message):
    labels = example("rallies")
    change(labels)
    with pytest.raises(ValidationError, match=message):
        RallyLabels.model_validate(labels)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda d: d.update(schema="dinkdata.rallies/v1"), id="wrong version"),
        pytest.param(lambda d: d.update(video_id="session-1234"), id="raw session id"),
        pytest.param(lambda d: d.update(labeller="Marti L"), id="labeller not a handle"),
        pytest.param(lambda d: d.update(notes="x"), id="unknown top-level field"),
        pytest.param(lambda d: rally(d, 1).update(comment="x"), id="unknown rally field"),
        pytest.param(lambda d: rally(d, 1)["serve"].update(server="p5"), id="fifth player"),
        pytest.param(lambda d: rally(d, 1)["serve"].update(side="middle"), id="unknown side"),
        pytest.param(lambda d: rally(d, 2).update(score_before="1-0-3"), id="server 3"),
        pytest.param(lambda d: rally(d, 1)["serve"].update(conf=1.5), id="conf above 1"),
        pytest.param(lambda d: rally(d, 1).update(start_t=-1.0), id="negative t"),
        pytest.param(lambda d: rally(d, 1).update(end_t=float("nan")), id="nan t"),
        pytest.param(
            lambda d: rally(d, 9)["rule_deviations"][0].update(type="foot_fault"),
            id="unknown deviation",
        ),
        pytest.param(
            lambda d: rally(d, 9)["rule_deviations"][0].update(note="Bob forgot"),
            id="free text on a deviation",
        ),
        pytest.param(lambda d: g1(d).update(target=12), id="unknown target"),
        pytest.param(lambda d: g1(d).pop("start_t"), id="game without start"),
        pytest.param(lambda d: rally(d, 1).pop("end_t"), id="rally without end"),
    ],
)
def test_schema_rejects(change):
    labels = example("rallies")
    change(labels)
    with pytest.raises(ValidationError):
        RallyLabels.model_validate(labels)
