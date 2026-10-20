"""The committed JSON Schemas in contracts/ must match the pydantic models."""

import pytest
from typer.testing import CliRunner

from dinkdata.cli import app
from dinkdata.contracts.export import generate_schemas
from tests.contracts.examples import CONTRACTS

GENERATED = generate_schemas()


@pytest.mark.parametrize("name", sorted(GENERATED))
def test_committed_schema_is_not_stale(name):
    path = CONTRACTS / f"{name}.schema.json"
    assert path.exists(), f"{path.name} is missing. Run `uv run dink contracts export`."
    assert path.read_text() == GENERATED[name], (
        f"{path.name} is stale. Run `uv run dink contracts export` and commit the result."
    )


def test_every_committed_schema_comes_from_a_model():
    committed = {p.name.removesuffix(".schema.json") for p in CONTRACTS.glob("*.schema.json")}
    assert committed <= set(GENERATED), committed - set(GENERATED)


def test_schemas_carry_their_names():
    for name, text in GENERATED.items():
        assert f'"$id": "https://github.com/roberto-cantero/dink-data/contracts/{name}' in text


runner = CliRunner()


def test_export_check_fails_until_exported(tmp_path):
    assert runner.invoke(app, ["contracts", "export", "--check", "--out", str(tmp_path)]).exit_code
    result = runner.invoke(app, ["contracts", "export", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    check = runner.invoke(app, ["contracts", "export", "--check", "--out", str(tmp_path)])
    assert check.exit_code == 0, check.output
