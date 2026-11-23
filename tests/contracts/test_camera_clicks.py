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
    assert len(FLOOR_KEYPOINTS) == 12
    assert NET_TOPS == ("net_top_left", "net_top_centre", "net_top_right")
    assert len(COURT_LINES) == 8
    assert all(isinstance(name, str) for name in FLOOR_KEYPOINTS + NET_TOPS + COURT_LINES)
    assert not set(FLOOR_KEYPOINTS) & set(NET_TOPS)


def test_accepts_every_named_point_and_line():
    data = example("camera_clicks")
    data["keypoints"] = {name: [960.0, 540.0] for name in FLOOR_KEYPOINTS}
    data["net_tops"] = {name: [960.0, 400.0] for name in NET_TOPS}
    data["line_points"] = {name: [[100.0, 100.0], [200.0, 200.0]] for name in COURT_LINES}
    clicks = CameraClicks.model_validate(data)
    assert list(clicks.keypoints) == list(FLOOR_KEYPOINTS)


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
            lambda d: d["line_points"]["far_baseline"].extend([[800.0, 212.0]] * 3), id="line of 6"
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
