"""The MP4 renderer: FFmpeg cuts, marks and joins a reel's clips (DESIGN 3.3, 6.12)."""

from datetime import date
from pathlib import Path

import cv2
import numpy as np
import pytest

from dinkdata.contracts.highlights import Clip, Reel
from dinkdata.highlights.render import TitleCard, render_reel
from dinkdata.video import ffmpeg
from tests.fixtures.ffmpeg_clips import needs_ffmpeg

CARD = TitleCard(photo_crop=None, game_number=1, date=date(2026, 10, 20))


def clip(clip_id: str, rally_id: str, start_t: float, end_t: float, **extra) -> Clip:
    row = {"reasons": ["winner"], "score": 1.0}
    row.update(extra)
    return Clip(id=clip_id, rally_id=rally_id, start_t=start_t, end_t=end_t, **row)


def reel(*clips: Clip) -> Reel:
    return Reel(game_id="g1", player_id="p1", clips=list(clips), mp4=None)


def probe_duration(path: Path) -> float:
    cap = cv2.VideoCapture(str(path))
    try:
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = cap.get(cv2.CAP_PROP_FPS)
        return frames / fps
    finally:
        cap.release()


@needs_ffmpeg
def test_render_reel_writes_a_joined_mp4(synthetic_clip, tmp_path):
    out = render_reel(
        synthetic_clip,
        reel(clip("g1_p1_c1", "g1_r1", 0.2, 0.8), clip("g1_p1_c2", "g1_r2", 1.0, 1.6)),
        CARD,
        tmp_path / "reel.mp4",
    )
    assert out.exists()
    # Title card (2.5s) plus two 0.6s clips, give or take a frame either way.
    assert probe_duration(out) == pytest.approx(0.6 + 0.6 + 2.5, abs=0.2)


@needs_ffmpeg
def test_render_reel_cleans_up_its_work_dir(synthetic_clip, tmp_path):
    out = tmp_path / "reel.mp4"
    render_reel(synthetic_clip, reel(clip("g1_p1_c1", "g1_r1", 0.2, 0.8)), CARD, out)
    assert not (tmp_path / f".{out.stem}.parts").exists()


@needs_ffmpeg
def test_render_reel_with_a_photo_crop(synthetic_clip, tmp_path):
    photo = tmp_path / "photo.png"
    cv2.imwrite(str(photo), np.full((40, 30, 3), 128, dtype=np.uint8))
    card = TitleCard(photo_crop=photo, game_number=2, date=date(2026, 10, 20))
    out = render_reel(
        synthetic_clip, reel(clip("g1_p1_c1", "g1_r1", 0.2, 0.8)), card, tmp_path / "reel.mp4"
    )
    assert out.exists()


@needs_ffmpeg
def test_render_reel_with_a_marker(synthetic_clip, tmp_path):
    the_clip = clip("g1_p1_c1", "g1_r1", 0.2, 0.8)
    out = render_reel(
        synthetic_clip,
        reel(the_clip),
        CARD,
        tmp_path / "reel.mp4",
        markers={the_clip.id: (160.0, 90.0)},
    )
    assert out.exists()


def test_render_reel_reports_missing_tools(synthetic_clip, tmp_path, monkeypatch):
    import dinkdata.highlights.render as render_module

    monkeypatch.setattr(render_module, "missing_tools", lambda: ["ffmpeg", "ffprobe"])
    with pytest.raises(ffmpeg.FfmpegError, match="ffmpeg, ffprobe"):
        render_reel(
            synthetic_clip, reel(clip("g1_p1_c1", "g1_r1", 0.2, 0.8)), CARD, tmp_path / "reel.mp4"
        )
