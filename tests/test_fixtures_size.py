from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def test_fixtures_stay_under_1mb():
    total = sum(p.stat().st_size for p in FIXTURES.rglob("*") if p.is_file())
    assert total < 1_000_000
