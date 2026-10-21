import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def court_json() -> dict:
    return json.loads((FIXTURES / "court.json").read_text())


@pytest.fixture
def events_json() -> dict:
    return json.loads((FIXTURES / "events.json").read_text())


@pytest.fixture
def synthetic_clip(tmp_path: Path) -> Path:
    from tests.fixtures.make_clip import make_clip

    return make_clip(tmp_path / "clip.mp4")


@pytest.fixture
def gappy_clip(tmp_path: Path) -> Path:
    from tests.fixtures.make_gappy_clip import make_gappy_clip

    return make_gappy_clip(tmp_path / "gappy.mp4")
