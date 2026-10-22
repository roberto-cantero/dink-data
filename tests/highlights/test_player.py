"""The simple reel web page: plays a reel's clips from clip times (DESIGN 6.12 point 1)."""

import json

from dinkdata.contracts.highlights import Clip, Reel
from dinkdata.highlights.player import write_player_page


def reel() -> Reel:
    return Reel(
        game_id="g1",
        player_id="p1",
        clips=[
            Clip(
                id="g1_p1_c1",
                rally_id="g1_r1",
                start_t=10.0,
                end_t=20.0,
                reasons=["winner"],
                score=1.0,
            ),
            Clip(
                id="g1_p1_c2",
                rally_id="g1_r5",
                start_t=40.0,
                end_t=55.0,
                reasons=["long_rally"],
                score=1.8,
            ),
        ],
        mp4=None,
    )


def test_write_player_page_embeds_the_clip_times(tmp_path):
    out = write_player_page(reel(), "video.mp4", tmp_path / "reel.html")
    page = out.read_text()
    assert 'src="video.mp4"' in page
    start, end = json.loads(page.split("const clips = ", 1)[1].split(";", 1)[0])
    assert (start["start_t"], start["end_t"]) == (10.0, 20.0)
    assert (end["start_t"], end["end_t"]) == (40.0, 55.0)
    assert end["reasons"] == ["long_rally"]


def test_write_player_page_escapes_the_video_src(tmp_path):
    out = write_player_page(reel(), 'x.mp4"><script>evil()</script>', tmp_path / "reel.html")
    page = out.read_text()
    assert "<script>evil()</script>" not in page
    assert "&lt;script&gt;evil()&lt;/script&gt;" in page


def test_write_player_page_uses_a_default_title(tmp_path):
    out = write_player_page(reel(), "video.mp4", tmp_path / "reel.html")
    assert "g1 / p1 reel" in out.read_text()


def test_write_player_page_accepts_a_custom_title(tmp_path):
    out = write_player_page(reel(), "video.mp4", tmp_path / "reel.html", title="My reel")
    assert "My reel" in out.read_text()
