import pytest
from typer.testing import CliRunner

from dinkdata.cli import PLACEHOLDERS, app

runner = CliRunner()


def test_help_lists_every_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in [*PLACEHOLDERS, "version"]:
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
