"""Every contracts/*.schema.json must have a *.example.json that validates against it."""

import json
from pathlib import Path

import jsonschema
import pytest

CONTRACTS = Path(__file__).parents[2] / "contracts"
SCHEMAS = sorted(CONTRACTS.glob("*.schema.json"))


def test_every_example_has_a_schema():
    for example in CONTRACTS.glob("*.example.json"):
        schema = example.with_name(example.name.replace(".example.json", ".schema.json"))
        assert schema.exists(), f"{example.name} has no matching schema"


@pytest.mark.parametrize("schema_path", SCHEMAS, ids=lambda p: p.name)
def test_example_matches_schema(schema_path: Path):
    example_path = schema_path.with_name(schema_path.name.replace(".schema.json", ".example.json"))
    assert example_path.exists(), f"{schema_path.name} has no {example_path.name}"
    schema = json.loads(schema_path.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(json.loads(example_path.read_text()), schema)
