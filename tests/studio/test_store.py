"""Versioned label files never overwrite each other."""

import pytest

from dinkdata.studio import store


def test_versions_count_up_and_never_overwrite(tmp_path):
    folder = store.rally_folder(tmp_path, "v_5eed00000000a001", "marti")
    first = store.write_new_version(folder, b"one", ".json")
    second = store.write_new_version(folder, b"two", ".json")
    assert (first.name, second.name) == ("v1.json", "v2.json")
    assert first.read_bytes() == b"one"
    assert store.latest(folder, ".json") == second
    assert first.relative_to(tmp_path).as_posix() == "gold-rallies/v_5eed00000000a001/marti/v1.json"


def test_versions_sort_by_number_and_ignore_other_files(tmp_path):
    for name in ["v2.json", "v10.json", "v1.json", "notes.json", "v3.png", "v0.json"]:
        (tmp_path / name).write_text("{}")
    assert store.versions(tmp_path, ".json") == [1, 2, 10]
    assert store.write_new_version(tmp_path, b"{}", ".json").name == "v11.json"


def test_no_folder_means_no_versions(tmp_path):
    assert store.versions(tmp_path / "missing", ".json") == []
    assert store.latest(tmp_path / "missing", ".json") is None


@pytest.mark.parametrize("player", ["../../etc", "p5", "", "p1/../p2"])
def test_crop_folders_exist_only_for_the_4_players(tmp_path, player):
    with pytest.raises(ValueError, match="player"):
        store.crop_folder(tmp_path, "v_5eed00000000a001", "marti", player)  # type: ignore[arg-type]


def test_crop_folders_sit_beside_the_labels(tmp_path):
    folder = store.crop_folder(tmp_path, "v_5eed00000000a001", "marti", "p3")
    assert (
        folder.relative_to(tmp_path).as_posix() == "gold-rallies/v_5eed00000000a001/marti/crops/p3"
    )
