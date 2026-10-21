"""`dink ingest` on the command line: hidden prompts, and nothing private in its output."""

import pytest
from typer.testing import CliRunner

from dinkdata.cli import app
from dinkdata.contracts import ids
from dinkdata.data import ingest, r2
from dinkdata.video import ffmpeg
from tests.fixtures.ffmpeg_clips import make_game_clip, needs_ffmpeg
from tests.fixtures.folder_store import FolderStore

SESSION = "SESSIONSECRET123"
FACILITY = "Secret Courts"
ANSWERS = f"{SESSION}\n{SESSION}\n{FACILITY}\n3\n"

runner = CliRunner()


@pytest.fixture
def store(tmp_path, monkeypatch):
    folder = FolderStore(tmp_path / "r2")
    monkeypatch.setenv(ids.ID_KEY_ENV, "k" * 16)
    monkeypatch.setattr(ingest, "missing_tools", lambda: [])
    monkeypatch.setattr(r2, "RcloneStore", lambda: folder)
    return folder


def run(tmp_path, video, *args):
    return runner.invoke(
        app,
        ["ingest", str(video), "--videos", str(tmp_path / "videos"), *args],
        input=ANSWERS,
    )


def assert_private(output: str) -> None:
    assert SESSION not in output
    assert FACILITY not in output


def test_missing_tools_are_named(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest, "missing_tools", lambda: ["ffmpeg", "ffprobe"])
    result = runner.invoke(app, ["ingest", str(tmp_path / "game.mp4")])
    assert result.exit_code == 1
    assert "brew install ffmpeg" in result.output


def test_without_the_id_key_it_fails(monkeypatch, tmp_path):
    monkeypatch.delenv(ids.ID_KEY_ENV, raising=False)
    monkeypatch.setattr(ingest, "missing_tools", lambda: [])
    result = runner.invoke(app, ["ingest", str(tmp_path / "game.mp4")])
    assert result.exit_code == 1
    assert ids.ID_KEY_ENV in result.output


def test_a_missing_file_is_reported_without_its_path(store, tmp_path):
    result = run(tmp_path, tmp_path / "court3_other.mp4")
    assert result.exit_code == 1
    assert "doesn't exist" in result.output
    assert "court3_other" not in result.output


def test_a_new_facility_without_a_split_fails(store, tmp_path):
    (tmp_path / "game.mp4").write_bytes(b"x")
    result = run(tmp_path, tmp_path / "game.mp4")
    assert result.exit_code == 1
    assert "--split" in result.output
    assert_private(result.output)


def test_ffmpeg_errors_are_shown_without_secrets(store, tmp_path, monkeypatch):
    def fail(source, _out):
        raise ffmpeg.FfmpegError("ffmpeg", f"{source}: bad data in court3_{SESSION} at {FACILITY}")

    monkeypatch.setattr(ffmpeg, "remux_video_only", fail)
    (tmp_path / "game.mp4").write_bytes(b"x")
    result = run(tmp_path, tmp_path / "game.mp4", "--split", "train")
    assert result.exit_code == 1
    assert "bad data" in result.output
    assert str(tmp_path / "game.mp4") not in result.output
    assert_private(result.output)


@needs_ffmpeg
def test_ingest_prints_only_opaque_ids_and_counts(store, tmp_path):
    video = make_game_clip(tmp_path / "game.mp4")
    result = run(tmp_path, video, "--split", "train")
    assert result.exit_code == 0, result.output
    video_id = ids.video_id(SESSION, b"k" * 16)
    assert result.output.strip().endswith(video_id)
    assert "1 dropped" in result.output
    assert f"Uploaded videos/{video_id}.mp4" in result.output
    assert_private(result.output)

    again = run(tmp_path, video)
    assert again.exit_code == 0, again.output
    assert "Nothing to do" in again.output
