"""Intake's ffmpeg steps: drop audio and metadata, time every frame, spot dropped and repeated
frames."""

import json
import subprocess
from fractions import Fraction

import pytest

from dinkdata.contracts.frames import FRAMES
from dinkdata.video import ffmpeg
from tests.fixtures.ffmpeg_clips import (
    DROPPED_FRAME,
    RATE,
    SECONDS,
    TITLE,
    make_game_clip,
    make_still_clip,
    needs_ffmpeg,
)

# A 1/15360 time base with 512 ticks a frame, as ffmpeg writes a 30 fps MP4.
TB = Fraction(1, 15360)
STEP = 512


def frames(pts, hashes=None):
    hashes = hashes or [str(i) for i in range(len(pts))]
    return ffmpeg.build_frames(pts, TB, hashes).to_pylist()


def test_steady_frames_have_no_drops_or_repeats():
    rows = frames([1024 + i * STEP for i in range(5)])
    assert [r["frame"] for r in rows] == [0, 1, 2, 3, 4]
    assert rows[0]["t"] == 0
    assert rows[2]["t"] == pytest.approx(2 * STEP / 15360)
    assert not any(r["dropped_before"] or r["duplicate"] for r in rows)


def test_a_double_gap_is_one_dropped_frame_and_a_triple_gap_two():
    rows = frames([0, STEP, 3 * STEP, 4 * STEP, 7 * STEP, 8 * STEP])
    assert [r["dropped_before"] for r in rows] == [0, 0, 1, 0, 2, 0]
    assert rows[2]["t"] == pytest.approx(3 * STEP / 15360)


def test_a_slightly_late_frame_is_not_a_drop():
    rows = frames([0, STEP, 2 * STEP + 40, 3 * STEP, 4 * STEP])
    assert [r["dropped_before"] for r in rows] == [0, 0, 0, 0, 0]


def test_a_repeated_picture_is_a_duplicate():
    rows = frames([0, STEP, 2 * STEP, 3 * STEP], ["a", "b", "b", "c"])
    assert [r["duplicate"] for r in rows] == [False, False, True, False]


def test_the_table_passes_the_frames_contract():
    table = ffmpeg.build_frames([0, STEP, 3 * STEP], TB, ["a", "b", "c"])
    assert FRAMES.errors(table) == []


def test_a_single_frame_works():
    assert frames([700]) == [{"frame": 0, "t": 0.0, "dropped_before": 0, "duplicate": False}]


@pytest.mark.parametrize(
    ("pts", "hashes"),
    [([], []), ([0, STEP], ["a"]), ([0, STEP, STEP], ["a", "b", "c"])],
    ids=["empty", "count-mismatch", "repeated-pts"],
)
def test_bad_input_is_rejected(pts, hashes):
    with pytest.raises(ValueError):
        ffmpeg.build_frames(pts, TB, hashes)


def test_nominal_fps_comes_from_the_usual_gap():
    pts = [0, STEP, 3 * STEP, 4 * STEP, 5 * STEP]
    assert ffmpeg.nominal_fps(pts, TB) == pytest.approx(30)


@needs_ffmpeg
def test_failures_keep_the_tools_message(tmp_path):
    with pytest.raises(ffmpeg.FfmpegError) as error:
        ffmpeg.probe(tmp_path / "missing.mp4")
    assert "missing.mp4" in error.value.stderr


def _streams(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)


@needs_ffmpeg
def test_remux_drops_audio_and_the_title(tmp_path):
    source = make_game_clip(tmp_path / "download.mp4")
    out = tmp_path / "out.mp4"
    ffmpeg.remux_video_only(source, out)
    info = _streams(out)
    assert [s["codec_type"] for s in info["streams"]] == ["video"]
    assert TITLE not in json.dumps(info)
    assert "SESSIONSECRET" not in out.read_bytes().decode("latin-1")


@needs_ffmpeg
def test_probe_times_every_frame_and_finds_the_cut_frame(tmp_path):
    out = tmp_path / "out.mp4"
    ffmpeg.remux_video_only(make_game_clip(tmp_path / "download.mp4"), out)
    info = ffmpeg.probe(out)
    table = ffmpeg.build_frames(info.pts, info.time_base, ffmpeg.frame_hashes(out))
    rows = table.to_pylist()
    assert len(rows) == SECONDS * RATE - 1
    assert [r["frame"] for r in rows if r["dropped_before"]] == [DROPPED_FRAME]
    assert rows[DROPPED_FRAME]["t"] == pytest.approx((DROPPED_FRAME + 1) / RATE, abs=1e-3)
    assert not any(r["duplicate"] for r in rows)
    assert info.duration_s == pytest.approx(SECONDS, abs=0.1)
    assert ffmpeg.nominal_fps(info.pts, info.time_base) == pytest.approx(RATE)


@needs_ffmpeg
def test_frame_hashes_spot_a_still_picture(tmp_path):
    clip = make_still_clip(tmp_path / "still.mp4")
    hashes = ffmpeg.frame_hashes(clip)
    assert len(hashes) == SECONDS * RATE
    assert len(set(hashes)) == 1
