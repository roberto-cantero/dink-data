"""The rclone store: commands it runs and how it reads rclone's exit codes."""

import subprocess
from pathlib import Path

import pytest

from dinkdata.data import r2


class FakeRclone:
    """Records each rclone call and answers with a fixed exit code and output."""

    def __init__(self, code: int = 0, stdout: str = "") -> None:
        self.calls: list[list[str]] = []
        self.code, self.stdout = code, stdout

    def __call__(self, args, **_kwargs):
        self.calls.append(list(args))
        return subprocess.CompletedProcess(args, self.code, self.stdout, "rclone said no")


@pytest.fixture
def fake(monkeypatch):
    def install(code: int = 0, stdout: str = "") -> FakeRclone:
        rclone = FakeRclone(code, stdout)
        monkeypatch.setattr(r2.subprocess, "run", rclone)
        return rclone

    return install


def test_exists_lists_the_folder_and_matches_the_exact_name(fake):
    rclone = fake(stdout="v_1.mp4\nv_10.mp4\n")
    store = r2.RcloneStore()
    assert store.exists("videos/v_1.mp4")
    assert not store.exists("videos/v_2.mp4")
    assert rclone.calls[0] == ["rclone", "lsf", "--files-only", "r2:dinkdata/videos"]


def test_a_missing_folder_means_the_file_is_missing(fake):
    fake(code=3)
    assert not r2.RcloneStore().exists("catalog/catalog.parquet")


def test_other_rclone_failures_raise(fake):
    fake(code=1)
    with pytest.raises(r2.RcloneError, match="rclone said no"):
        r2.RcloneStore().exists("videos/v_1.mp4")


def test_put_never_overwrites_unless_asked(fake):
    rclone = fake()
    store = r2.RcloneStore()
    store.put(Path("local.mp4"), "videos/v_1.mp4")
    store.put(Path("catalog.parquet"), "catalog/catalog.parquet", overwrite=True)
    assert rclone.calls == [
        ["rclone", "copyto", "--immutable", "local.mp4", "r2:dinkdata/videos/v_1.mp4"],
        ["rclone", "copyto", "catalog.parquet", "r2:dinkdata/catalog/catalog.parquet"],
    ]


def test_get_copies_to_the_local_path(fake):
    rclone = fake()
    r2.RcloneStore().get("catalog/id_map.parquet", Path("here.parquet"))
    assert rclone.calls == [
        ["rclone", "copyto", "r2:dinkdata/catalog/id_map.parquet", "here.parquet"]
    ]
