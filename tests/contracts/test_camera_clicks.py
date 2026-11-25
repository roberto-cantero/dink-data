"""clicks.json: the raw clicks one calibration was fitted from."""

import json

import pytest
from pydantic import ValidationError

from dinkdata.contracts.camera_clicks import (
    COURT_LINES,
    FLOOR_KEYPOINTS,
    NET_TOPS,
    CameraClicks,
)
from dinkdata.contracts.common import dump, load
from tests.contracts.examples import example


def test_example_round_trips(tmp_path):
    clicks = CameraClicks.model_validate(example("camera_clicks"))
    dump(clicks, tmp_path / "clicks.json")
    assert json.loads((tmp_path / "clicks.json").read_text()) == example("camera_clicks")
    assert load(CameraClicks, tmp_path / "clicks.json") == clicks


def test_names_match_court_md():
    assert FLOOR_KEYPOINTS == (
        "far_left_corner",
        "far_right_corner",
        "near_right_corner",
        "near_left_corner",
        "far_kitchen_left",
        "far_kitchen_right",
        "near_kitchen_right",
        "near_kitchen_left",
        "far_kitchen_centre",
        "near_kitchen_centre",
        "far_baseline_centre",
        "near_baseline_centre",
    )
    assert NET_TOPS == ("net_top_left", "net_top_centre", "net_top_right")
    assert COURT_LINES == (
        "far_baseline",
        "near_baseline",
        "left_sideline",
        "right_sideline",
        "far_kitchen_line",
        "near_kitchen_line",
        "far_centre_line",
        "near_centre_line",
    )


def test_accepts_every_named_point_and_line():
    data = example("camera_clicks")
    data["keypoints"] = {name: [960.0, 540.0] for name in FLOOR_KEYPOINTS}
    data["net_tops"] = {name: [960.0, 400.0] for name in NET_TOPS}
    data["line_points"] = {name: [[100.0, 100.0], [200.0, 200.0]] for name in COURT_LINES}
    clicks = CameraClicks.model_validate(data)
    assert list(clicks.keypoints) == list(FLOOR_KEYPOINTS)


def test_a_line_may_have_more_than_5_points():
    data = example("camera_clicks")
    data["line_points"]["far_baseline"] = [[800.0 + 50 * n, 454.0] for n in range(6)]
    assert len(CameraClicks.model_validate(data).line_points["far_baseline"]) == 6


def test_single_frame_is_null_when_never_used():
    data = example("camera_clicks")
    data["single_frame"] = None
    assert CameraClicks.model_validate(data).single_frame is None


def test_skipped_points_are_absent():
    data = example("camera_clicks")
    data.update(keypoints={}, line_points={}, net_tops={}, overlay_rects=[])
    clicks = CameraClicks.model_validate(data)
    assert clicks.keypoints == {}


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda d: d.update(schema="dinkdata.camera_clicks/v2"), id="wrong schema"),
        pytest.param(lambda d: d.update(camera_id="court1"), id="raw camera id"),
        pytest.param(lambda d: d.update(video_id="match.mp4"), id="raw video id"),
        pytest.param(lambda d: d.update(version=0), id="version 0"),
        pytest.param(lambda d: d.update(frames=[]), id="no frames"),
        pytest.param(lambda d: d.update(frames=[-1]), id="negative frame"),
        pytest.param(lambda d: d.update(frames=[9720, 120]), id="frames out of order"),
        pytest.param(lambda d: d.update(frames=[120, 120]), id="repeated frame"),
        pytest.param(lambda d: d.pop("single_frame"), id="single frame missing"),
        pytest.param(lambda d: d.update(single_frame=-1), id="negative single frame"),
        pytest.param(lambda d: d["image_size"].update(width=0), id="zero width"),
        pytest.param(lambda d: d["keypoints"].update(corner_5=[10.0, 10.0]), id="unknown keypoint"),
        pytest.param(
            lambda d: d["keypoints"].update(net_top_left=[10.0, 10.0]), id="net top as keypoint"
        ),
        pytest.param(
            lambda d: d["line_points"].update(net_line=[[1.0, 1.0], [2.0, 2.0]]),
            id="unknown court line",
        ),
        pytest.param(
            lambda d: d["net_tops"].update(far_left_corner=[10.0, 10.0]), id="keypoint as net top"
        ),
        pytest.param(
            lambda d: d["keypoints"].update(far_left_corner=[1921.0, 200.0]), id="keypoint right"
        ),
        pytest.param(
            lambda d: d["keypoints"].update(far_left_corner=[700.0, -0.5]), id="keypoint above"
        ),
        pytest.param(
            lambda d: d["line_points"]["far_baseline"].append([10.0, 1081.0]), id="line point below"
        ),
        pytest.param(
            lambda d: d["net_tops"].update(net_top_left=[-3.0, 400.0]), id="net top left of image"
        ),
        pytest.param(
            lambda d: d["keypoints"].update(far_left_corner=[float("nan"), 200.0]), id="nan pixel"
        ),
        pytest.param(
            lambda d: d["line_points"].update(far_kitchen_line=[[700.0, 379.5]]), id="line of 1"
        ),
        pytest.param(
            lambda d: d["overlay_rects"].append([1900.0, 20.0, 1700.0, 90.0]), id="rect backwards"
        ),
        pytest.param(
            lambda d: d["overlay_rects"].append([1700.0, 20.0, 1700.0, 90.0]), id="rect no width"
        ),
        pytest.param(
            lambda d: d["overlay_rects"].append([1700.0, 20.0, 1950.0, 90.0]), id="rect outside"
        ),
        pytest.param(lambda d: d.update(labeller="Robby C"), id="bad handle"),
        pytest.param(lambda d: d.update(saved_at="2026-11-23T14:05:00"), id="naive time"),
        pytest.param(lambda d: d.update(setup="dtl_low"), id="unknown field"),
    ],
)
def test_rejects(change):
    data = example("camera_clicks")
    change(data)
    with pytest.raises(ValidationError):
        CameraClicks.model_validate(data)
