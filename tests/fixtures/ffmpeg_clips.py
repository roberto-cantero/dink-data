"""Tiny synthetic MP4s made with ffmpeg's built-in sources, for intake tests (no real footage).

Each clip has an audio track and a title, like a real download, so tests can check that intake
drops both. Tests that use these skip when ffmpeg isn't installed.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

TITLE = "court3_SESSIONSECRET123"
SECONDS = 2
RATE = 30
DROPPED_FRAME = 10

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="needs ffmpeg and ffprobe (brew install ffmpeg)",
)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args], check=True)


def make_game_clip(path: Path) -> Path:
    """A moving test pattern with a tone and a title. Frame 10 is cut out, which leaves a
    double-length gap in the timestamps, like a frame the camera dropped."""
    _ffmpeg(
        "-f", "lavfi", "-i", f"testsrc2=size=160x90:rate={RATE}:duration={SECONDS}",
        "-f", "lavfi", "-i", f"sine=duration={SECONDS}",
        "-vf", f"select='not(eq(n\\,{DROPPED_FRAME}))'",
        "-fps_mode", "passthrough",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-metadata", f"title={TITLE}",
        str(path),
    )  # fmt: skip
    return path


def make_still_clip(path: Path) -> Path:
    """One colour for every frame, encoded losslessly, so each frame repeats the one before."""
    _ffmpeg(
        "-f", "lavfi", "-i", f"color=c=green:size=160x90:rate={RATE}:duration={SECONDS}",
        "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p",
        str(path),
    )  # fmt: skip
    return path
