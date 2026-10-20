"""highlights.json: one reel of clips per game per player."""

import json

import pytest
from pydantic import ValidationError

from dinkdata.contracts.common import dump, load
from dinkdata.contracts.game_log import EventLog
from dinkdata.contracts.highlights import Highlights, check_highlights
from dinkdata.contracts.rallies import RallyLabels
from tests.contracts.examples import example


def clip(h: dict, reel: int, n: int) -> dict:
    return h["reels"][reel]["clips"][n - 1]


def test_example_round_trips(tmp_path):
    highlights = Highlights.model_validate(example("highlights"))
    dump(highlights, tmp_path / "highlights.json")
    assert json.loads((tmp_path / "highlights.json").read_text()) == example("highlights")
    assert load(Highlights, tmp_path / "highlights.json") == highlights


def test_example_fits_the_rally_labels():
    highlights = Highlights.model_validate(example("highlights"))
    assert check_highlights(highlights, RallyLabels.model_validate(example("rallies"))) == []


def test_a_game_log_works_as_the_timeline_too():
    log = EventLog.model_validate(example("events"))
    r1 = log.games[0].rallies[0]
    highlights = Highlights.model_validate(
        {
            "schema": "dinkdata.highlights/v1",
            "video_id": log.video.id,
            "reels": [
                {
                    "game_id": "g1",
                    "player_id": "p1",
                    "clips": [
                        {
                            "id": "g1_p1_c1",
                            "rally_id": r1.id,
                            "start_t": r1.start_t - 1.0,
                            "end_t": r1.end_t + 1.5,
                            "start_frame": None,
                            "end_frame": None,
                            "reasons": ["serve_point"],
                            "score": 1.0,
                        }
                    ],
                    "mp4": None,
                }
            ],
        }
    )
    assert check_highlights(highlights, log) == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(lambda d: d.update(video_id="v_5eed00000000ffff"), "video", id="other video"),
        pytest.param(lambda d: clip(d, 0, 2).update(rally_id="g1_r99"), "g1_r99", id="no rally"),
        pytest.param(lambda d: clip(d, 0, 1).update(start_t=126.0), "whole rally", id="late start"),
        pytest.param(lambda d: clip(d, 0, 1).update(end_t=135.0), "whole rally", id="early end"),
        pytest.param(lambda d: clip(d, 0, 1).update(end_t=152.0), "next serve", id="into next"),
    ],
)
def test_cross_file_rules(change, message):
    highlights = example("highlights")
    change(highlights)
    errors = check_highlights(
        Highlights.model_validate(highlights), RallyLabels.model_validate(example("rallies"))
    )
    assert any(message in error for error in errors), errors


def test_cross_file_rules_catch_a_missing_game():
    highlights = example("highlights")
    labels = example("rallies")
    labels["games"].pop(0)
    errors = check_highlights(
        Highlights.model_validate(highlights), RallyLabels.model_validate(labels)
    )
    assert any("g1" in error for error in errors), errors


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(lambda d: d["reels"][0]["clips"].reverse(), "order", id="clips out of order"),
        pytest.param(lambda d: clip(d, 0, 2).update(start_t=130.0), "overlap", id="clips overlap"),
        pytest.param(lambda d: clip(d, 0, 1).update(id="g1_p2_c1"), "g1_p1_", id="clip id prefix"),
        pytest.param(lambda d: clip(d, 0, 1).update(rally_id="g2_r1"), "g1_", id="other game"),
        pytest.param(lambda d: clip(d, 0, 1).update(end_t=100.0), "end_t", id="ends first"),
        pytest.param(lambda d: d["reels"].append(d["reels"][0]), "one reel", id="duplicate reel"),
        pytest.param(
            lambda d: clip(d, 1, 1).update(id="g1_p1_c1"),
            "g1_p2_",
            id="clip id from another reel",
        ),
        pytest.param(
            lambda d: clip(d, 0, 1).update(reasons=["ace", "ace"]), "unique", id="repeated reason"
        ),
    ],
)
def test_rules_within_the_file(change, message):
    highlights = example("highlights")
    change(highlights)
    with pytest.raises(ValidationError, match=message):
        Highlights.model_validate(highlights)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda d: d.update(schema="dinkdata.highlights/v2"), id="wrong version"),
        pytest.param(lambda d: d["reels"][0].update(clips=[]), id="empty reel"),
        pytest.param(lambda d: clip(d, 0, 1).update(reasons=[]), id="no reason"),
        pytest.param(lambda d: clip(d, 0, 1).update(reasons=["cool"]), id="unknown reason"),
        pytest.param(lambda d: clip(d, 0, 1).update(score=-1), id="negative score"),
        pytest.param(lambda d: d["reels"][0]["mp4"].update(path="/etc/x.mp4"), id="absolute path"),
        pytest.param(lambda d: d["reels"][0]["mp4"].update(path="../x.mp4"), id="parent path"),
        pytest.param(
            lambda d: d["reels"][0]["mp4"].update(rendered_at="2026-10-20T09:15:00"),
            id="time without zone",
        ),
        pytest.param(lambda d: d["reels"][0].update(player_id="p0"), id="unknown player"),
    ],
)
def test_schema_rejects(change):
    highlights = example("highlights")
    change(highlights)
    with pytest.raises(ValidationError):
        Highlights.model_validate(highlights)
