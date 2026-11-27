"""The versioned save in R2: If-None-Match writes that take the next number when refused.

Run through the folder store, which checks If-None-Match the way R2 does.
"""

import json

import pytest

from dinkdata.data import r2
from tests.fixtures.folder_store import FolderStore

FOLDER = "cameras/c_5eed00000000c0de"


def version_files(n: int) -> dict[str, bytes]:
    """Two files per version that each name their version, as calibrations do."""
    return {
        f"v{n}/clicks.json": json.dumps({"version": n, "file": "clicks"}).encode(),
        f"v{n}/camera.json": json.dumps({"version": n, "file": "camera"}).encode(),
    }


def read(store: FolderStore, path: str) -> dict:
    return json.loads((store.root / path).read_text())


@pytest.fixture
def store(tmp_path):
    return FolderStore(tmp_path / "r2")


def put(store: FolderStore, path: str, data: dict) -> None:
    target = store.root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data))


def test_the_first_save_is_v1_with_every_file(store):
    assert r2.put_new_version(store, FOLDER, version_files) == 1
    assert read(store, f"{FOLDER}/v1/clicks.json") == {"version": 1, "file": "clicks"}
    assert read(store, f"{FOLDER}/v1/camera.json") == {"version": 1, "file": "camera"}
    assert store.puts == [f"{FOLDER}/v1/clicks.json", f"{FOLDER}/v1/camera.json"]


def test_a_save_numbers_after_the_highest_version_in_the_store(store):
    put(store, f"{FOLDER}/v1/camera.json", {"old": 1})
    put(store, f"{FOLDER}/v7/camera.json", {"old": 7})
    put(store, f"{FOLDER}/notes.txt", {"not": "a version"})
    assert r2.versions(store, FOLDER) == [1, 7]
    assert r2.put_new_version(store, FOLDER, version_files) == 8
    assert read(store, f"{FOLDER}/v8/camera.json")["version"] == 8


def test_versions_read_flat_files_as_well_as_folders(store):
    put(store, "labels/gold-rallies/v_5eed00000000a001/marti/v2.json", {})
    put(store, "labels/gold-rallies/v_5eed00000000a001/marti/v10.json", {})
    put(store, "labels/gold-rallies/v_5eed00000000a001/marti/crops/p1/v3.png", {})
    assert r2.versions(store, "labels/gold-rallies/v_5eed00000000a001/marti") == [2, 10]


def test_after_skips_versions_known_elsewhere(store):
    put(store, f"{FOLDER}/v2/camera.json", {"old": 2})
    assert r2.put_new_version(store, FOLDER, version_files, after=5) == 6


def test_a_refused_write_takes_the_next_number_and_never_overwrites(store):
    put(store, f"{FOLDER}/v1/camera.json", {"old": 1})
    others = {"version": 2, "file": "someone else's"}

    def another_save_first(path: str) -> None:
        # Another Mac claims v2 between this save's listing and its write.
        if path == f"{FOLDER}/v2/clicks.json":
            put(store, path, others)
            store.before_write = None

    store.before_write = another_save_first
    assert r2.put_new_version(store, FOLDER, version_files) == 3
    assert read(store, f"{FOLDER}/v2/clicks.json") == others
    assert not (store.root / FOLDER / "v2" / "camera.json").exists()
    assert read(store, f"{FOLDER}/v3/clicks.json") == {"version": 3, "file": "clicks"}
    assert read(store, f"{FOLDER}/v3/camera.json") == {"version": 3, "file": "camera"}


def test_a_save_gives_up_when_every_number_is_taken(store):
    def always_first(path: str) -> None:
        put(store, path, {"taken": True})

    store.before_write = always_first
    with pytest.raises(r2.RcloneError, match="another save"):
        r2.put_new_version(store, FOLDER, version_files, attempts=3)


def test_a_later_file_already_there_stops_the_save(store):
    def camera_already_there(path: str) -> None:
        if path.endswith("camera.json"):
            put(store, path, {"stray": True})

    store.before_write = camera_already_there
    with pytest.raises(r2.RcloneError, match="camera.json"):
        r2.put_new_version(store, FOLDER, version_files)
    assert read(store, f"{FOLDER}/v1/camera.json") == {"stray": True}


def test_files_lists_a_folder_recursively_through_rclone(monkeypatch):
    import subprocess

    calls = []

    def fake(args, **_kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, "v2/camera.json\nv1/camera.json\n", "")

    monkeypatch.setattr(r2.subprocess, "run", fake)
    assert r2.RcloneStore().files(FOLDER) == ["v1/camera.json", "v2/camera.json"]
    assert calls[0] == ["rclone", "lsf", "-R", "--files-only", f"r2:dinkdata/{FOLDER}"]
