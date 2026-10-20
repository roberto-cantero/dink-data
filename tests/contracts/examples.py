"""Fresh copies of the committed synthetic examples, for tests that change them."""

import json
from pathlib import Path
from typing import Any

CONTRACTS = Path(__file__).parents[2] / "contracts"


def example(name: str) -> Any:
    return json.loads((CONTRACTS / f"{name}.example.json").read_text())
