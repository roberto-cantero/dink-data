"""load_camera reads a validated calibration from data/cameras/."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dinkdata.court.floor import load_camera
from tests.court.cameras import CAMERA_ID, camera_json


def save(root: Path, version: int, **changes) -> None:
    data = camera_json((0.1, 0.0, 0.0), (0.0, 0.0, 50.0), version=version)
    data.update(changes)
    folder = root / CAMERA_ID / f"v{version}"
    folder.mkdir(parents=True)
    (folder / "camera.json").write_text(json.dumps(data))


def test_latest_version_when_none_is_given(tmp_path):
    for version in (1, 2, 10):
        save(tmp_path, version)
    assert load_camera(CAMERA_ID, root=tmp_path).version == 10


def test_a_given_version(tmp_path):
    for version in (1, 2):
        save(tmp_path, version)
    assert load_camera(CAMERA_ID, 1, root=tmp_path).version == 1


def test_an_invalid_file_is_rejected(tmp_path):
    save(tmp_path, 1, setup="overhead")
    with pytest.raises(ValidationError):
        load_camera(CAMERA_ID, root=tmp_path)


def test_a_file_in_the_wrong_folder_is_rejected(tmp_path):
    save(tmp_path, 2)
    (tmp_path / CAMERA_ID / "v2").rename(tmp_path / CAMERA_ID / "v3")
    with pytest.raises(ValueError, match="v3"):
        load_camera(CAMERA_ID, root=tmp_path)


def test_a_missing_camera_says_how_to_fetch_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="rclone"):
        load_camera(CAMERA_ID, root=tmp_path)
    save(tmp_path, 1)
    with pytest.raises(FileNotFoundError, match="v2"):
        load_camera(CAMERA_ID, 2, root=tmp_path)
