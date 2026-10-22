"""`dink highlights build|render|player` (DESIGN 6.12)."""

import json

from typer.testing import CliRunner

from dinkdata.cli import app
from tests.contracts.examples import example
from tests.fixtures.ffmpeg_clips import needs_ffmpeg

runner = CliRunner()
VIDEO_ID = "v_5eed00000000a001"


def write_json(path, data) -> None:
    path.write_text(json.dumps(data))


def test_build_writes_highlights_json(tmp_path):
    rallies = tmp_path / "rallies.json"
    write_json(rallies, example("rallies"))
    picks = tmp_path / "picks.json"
    write_json(
        picks,
        {
            "video_id": VIDEO_ID,
            "picks": [
                {
                    "game_id": "g1",
                    "player_id": "p1",
                    "rally_id": "g1_r1",
                    "reasons": ["winner"],
                    "score": 1.0,
                }
            ],
        },
    )
    out = tmp_path / "highlights.json"
    result = runner.invoke(
        app,
        [
            "highlights", "build",
            "--picks", str(picks),
            "--rallies", str(rallies),
            "--out", str(out),
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text())
    assert data["schema"] == "dinkdata.highlights/v2"
    assert data["reels"][0]["player_id"] == "p1"


def test_build_reports_an_unknown_rally(tmp_path):
    rallies = tmp_path / "rallies.json"
    write_json(rallies, example("rallies"))
    picks = tmp_path / "picks.json"
    write_json(
        picks,
        {
            "video_id": VIDEO_ID,
            "picks": [
                {
                    "game_id": "g1",
                    "player_id": "p1",
                    "rally_id": "g1_r99",
                    "reasons": ["winner"],
                    "score": 1.0,
                }
            ],
        },
    )
    result = runner.invoke(
        app, ["highlights", "build", "--picks", str(picks), "--rallies", str(rallies)]
    )
    assert result.exit_code == 1
    assert "g1_r99" in result.output


def highlights_json(**clip_overrides) -> dict:
    clip = {
        "id": "g1_p1_c1",
        "rally_id": "g1_r1",
        "start_t": 0.2,
        "end_t": 0.8,
        "start_frame": None,
        "end_frame": None,
        "reasons": ["winner"],
        "score": 1.0,
    }
    clip.update(clip_overrides)
    return {
        "schema": "dinkdata.highlights/v2",
        "video_id": VIDEO_ID,
        "reels": [{"game_id": "g1", "player_id": "p1", "clips": [clip], "mp4": None}],
    }


@needs_ffmpeg
def test_render_writes_an_mp4(synthetic_clip, tmp_path):
    highlights = tmp_path / "highlights.json"
    write_json(highlights, highlights_json())
    out_dir = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "highlights", "render",
            "--highlights", str(highlights),
            "--video", str(synthetic_clip),
            "--game-number", "1",
            "--date", "2026-10-20",
            "--out-dir", str(out_dir),
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert (out_dir / "g1_p1.mp4").exists()


def test_render_rejects_a_bad_date(tmp_path):
    highlights = tmp_path / "highlights.json"
    write_json(highlights, highlights_json())
    result = runner.invoke(
        app,
        [
            "highlights", "render",
            "--highlights", str(highlights),
            "--video", str(tmp_path / "video.mp4"),
            "--game-number", "1",
            "--date", "not-a-date",
        ],
    )  # fmt: skip
    assert result.exit_code == 1


def test_render_reports_no_matching_reel(tmp_path):
    highlights = tmp_path / "highlights.json"
    write_json(highlights, highlights_json())
    result = runner.invoke(
        app,
        [
            "highlights", "render",
            "--highlights", str(highlights),
            "--video", str(tmp_path / "video.mp4"),
            "--game-number", "1",
            "--date", "2026-10-20",
            "--player", "p2",
        ],
    )  # fmt: skip
    assert result.exit_code == 1
    assert "No matching reel" in result.output


def test_player_writes_a_page(tmp_path):
    highlights = tmp_path / "highlights.json"
    write_json(highlights, highlights_json())
    out = tmp_path / "reel.html"
    result = runner.invoke(
        app,
        [
            "highlights", "player",
            "--highlights", str(highlights),
            "--game", "g1",
            "--player", "p1",
            "--video-src", "video.mp4",
            "--out", str(out),
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert out.exists()


def test_player_reports_no_matching_reel(tmp_path):
    highlights = tmp_path / "highlights.json"
    write_json(highlights, highlights_json())
    result = runner.invoke(
        app,
        [
            "highlights", "player",
            "--highlights", str(highlights),
            "--game", "g1",
            "--player", "p2",
            "--video-src", "video.mp4",
        ],
    )  # fmt: skip
    assert result.exit_code == 1
    assert "No reel" in result.output
