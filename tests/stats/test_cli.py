"""`dink stats`: events.json in, stats.json out."""

from typer.testing import CliRunner

from dinkdata.cli import app
from dinkdata.contracts.common import load, to_json
from dinkdata.contracts.stats import Stats
from tests.stats.logs import bounce, game_log, hit, rally

runner = CliRunner()


def test_stats_writes_stats_json(tmp_path):
    events = tmp_path / "events.json"
    events.write_text(to_json(game_log([rally(hit("p1", 1), bounce(5, 8))])))
    out = tmp_path / "stats.json"
    result = runner.invoke(
        app, ["stats", "--events", str(events), "--run-id", "test-run", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    stats = load(Stats, out)
    assert stats.run_id == "test-run"
    assert len(stats.stats) == 4 * 9
    assert "stats shipped" in result.output


def test_stats_rejects_a_bad_run_id(tmp_path):
    events = tmp_path / "events.json"
    events.write_text(to_json(game_log([rally(hit("p1", 1), bounce(5, 8))])))
    result = runner.invoke(app, ["stats", "--events", str(events), "--run-id", "no spaces"])
    assert result.exit_code == 1
    assert "run_id" in result.output
