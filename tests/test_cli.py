import pytest
from typer.testing import CliRunner

from dinkdata.cli import PLACEHOLDERS, app

runner = CliRunner()


def test_help_lists_every_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in [*PLACEHOLDERS, "version", "studio", "id"]:
        assert name in result.output


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip()


@pytest.mark.parametrize("name", sorted(PLACEHOLDERS))
def test_placeholders_say_not_built_and_fail(name):
    result = runner.invoke(app, [name])
    assert result.exit_code == 1
    assert "not built yet" in result.output


def test_studio_without_rally_mode_options_fails():
    result = runner.invoke(app, ["studio"])
    assert result.exit_code == 1
    assert "rally mode" in result.output


def test_studio_rejects_a_raw_id(tmp_path):
    (tmp_path / "1234.mp4").write_bytes(b"")
    result = runner.invoke(
        app, ["studio", "--rallies", "1234", "--labeller", "marti", "--videos", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "not a video id" in result.output


def test_studio_finds_the_video_by_id(tmp_path):
    result = runner.invoke(
        app,
        [
            "studio",
            "--rallies",
            "v_5eed00000000a001",
            "--labeller",
            "marti",
            "--videos",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 1
    assert "v_5eed00000000a001.mp4" in result.output
