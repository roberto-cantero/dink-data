"""camera.json: one calibration of one camera."""

import json

import pytest
from pydantic import ValidationError

from dinkdata.contracts.camera import CameraCalibration, check_log_camera
from dinkdata.contracts.common import dump, load
from dinkdata.contracts.game_log import EventLog
from tests.contracts.examples import example


def test_example_round_trips(tmp_path):
    camera = CameraCalibration.model_validate(example("camera"))
    dump(camera, tmp_path / "camera.json")
    assert json.loads((tmp_path / "camera.json").read_text()) == example("camera")
    assert load(CameraCalibration, tmp_path / "camera.json") == camera


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda d: d.update(version=0), id="version 0"),
        pytest.param(lambda d: d.update(camera_id="court1"), id="raw camera id"),
        pytest.param(lambda d: d.update(setup="overhead"), id="unknown setup"),
        pytest.param(lambda d: d["intrinsics"].update(fx=0), id="zero focal length"),
        pytest.param(lambda d: d["intrinsics"].update(cx=2500.0), id="centre outside"),
        pytest.param(lambda d: d["distortion"].update(k3=0.01), id="k3"),
        pytest.param(lambda d: d.update(rotation=[1.0, 0.0]), id="two rotation values"),
        pytest.param(lambda d: d.update(reprojection_error_px=-1), id="negative error"),
        pytest.param(lambda d: d.update(visible_region=[[0, 0], [20, 0]]), id="region of 2"),
        pytest.param(lambda d: d["overlay_masks"][0].append([2000.0, 50.0]), id="mask outside"),
        pytest.param(lambda d: d.update(source="guess"), id="unknown source"),
    ],
)
def test_rejects(change):
    data = example("camera")
    change(data)
    with pytest.raises(ValidationError):
        CameraCalibration.model_validate(data)


def test_events_json_names_its_calibration():
    log = EventLog.model_validate(example("events"))
    camera = CameraCalibration.model_validate(example("camera"))
    assert check_log_camera(log, camera) == []
    older = camera.model_copy(update={"version": 1})
    assert check_log_camera(log, older)
