"""ffmpeg and ffprobe for intake: drop the audio, time every frame and spot repeated frames.

The tools come from Homebrew on a Mac (`brew install ffmpeg`) and from apt on Linux. Every call
passes its arguments as a list, with no shell, and keeps the tool's message for errors.

Timestamps come from the video packets, sorted into display order, so reading them needs no
decoding. `frame_hashes` decodes every frame once, and its count must match, so the frame table
lists exactly the frames a decoder produces (DESIGN 6.1, ADR 0005).
"""

import json
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
import pyarrow as pa

from dinkdata.contracts.common import t_from_pts
from dinkdata.contracts.frames import FRAMES

TOOLS = ("ffmpeg", "ffprobe")


class FfmpegError(RuntimeError):
    """An ffmpeg or ffprobe call failed. `stderr` is the tool's own message."""

    def __init__(self, tool: str, stderr: str) -> None:
        super().__init__(f"{tool} failed: {stderr.strip()}")
        self.stderr = stderr


@dataclass(frozen=True)
class VideoInfo:
    """What ffprobe reports for a video's first video stream."""

    time_base: Fraction
    pts: list[int]
    """Every frame's presentation timestamp, in display order."""
    duration_s: float


def missing_tools() -> list[str]:
    return [tool for tool in TOOLS if shutil.which(tool) is None]


def _run(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise FfmpegError(args[0], result.stderr)
    return result.stdout


def remux_video_only(source: Path, out: Path) -> None:
    """Copy the first video stream to `out` without re-encoding it.

    `-map 0:v:0` keeps only that stream, so the audio is dropped (ADR 0008). Metadata and
    chapters are dropped too, because a download's title can hold the session id. The file is
    written next to `out` first and moved into place, so a failed run leaves no half file.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(f"{out.stem}.partial{out.suffix}")
    _run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y",
            "-i", str(source),
            "-map", "0:v:0", "-c", "copy",
            "-map_metadata", "-1", "-map_chapters", "-1",
            "-movflags", "+faststart",
            str(partial),
        ]
    )  # fmt: skip
    partial.replace(out)


def probe(path: Path) -> VideoInfo:
    """Read the time base, every frame's timestamp and the duration of the first video stream."""
    out = _run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=time_base:format=duration:packet=pts",
            "-of", "json", str(path),
        ]
    )  # fmt: skip
    data = json.loads(out)
    streams = data.get("streams") or []
    if not streams:
        raise FfmpegError("ffprobe", "the file has no video stream")
    packets = data.get("packets") or []
    if any("pts" not in p for p in packets):
        raise FfmpegError("ffprobe", "a video packet has no timestamp")
    return VideoInfo(
        time_base=Fraction(streams[0]["time_base"]),
        pts=sorted(int(p["pts"]) for p in packets),
        duration_s=float(data.get("format", {}).get("duration", 0)),
    )


def frame_hashes(path: Path) -> list[str]:
    """An MD5 of every decoded picture of the first video stream, in display order.

    `-fps_mode passthrough` stops ffmpeg from adding or removing frames to fit a frame rate.
    """
    out = _run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-v", "error",
            "-i", str(path), "-map", "0:v:0",
            "-fps_mode", "passthrough", "-f", "framemd5", "-",
        ]
    )  # fmt: skip
    return [line.rsplit(",", 1)[1].strip() for line in out.splitlines() if not line.startswith("#")]


def _usual_gap(pts: Sequence[int]) -> float:
    """The median gap between frames, in time-base ticks: the nominal frame length."""
    return float(np.median(np.diff(np.asarray(pts, dtype=np.int64))))


def nominal_fps(pts: Sequence[int], time_base: Fraction) -> float:
    """The frame rate the camera aimed for, from the usual gap. Never use it for time."""
    if len(pts) < 2:
        raise ValueError("a frame rate needs at least two frames")
    return 1 / (_usual_gap(pts) * float(time_base))


def build_frames(pts: Sequence[int], time_base: Fraction, hashes: Sequence[str]) -> pa.Table:
    """The frames.parquet table from sorted timestamps and each frame's picture hash.

    A gap of about n usual frame lengths means n - 1 frames were dropped before that frame. A
    frame whose hash equals the previous frame's is a duplicate.
    """
    if not pts:
        raise ValueError("the video has no frames")
    if len(pts) != len(hashes):
        raise ValueError(f"{len(pts)} timestamps but {len(hashes)} decoded frames")
    gaps = np.diff(np.asarray(pts, dtype=np.int64))
    if np.any(gaps <= 0):
        raise ValueError("frame timestamps repeat or go backwards")
    dropped = [0]
    if len(gaps):
        dropped += np.maximum(np.rint(gaps / _usual_gap(pts)).astype(np.int64) - 1, 0).tolist()
    table = pa.Table.from_pydict(
        {
            "frame": list(range(len(pts))),
            "t": [t_from_pts(p, pts[0], time_base) for p in pts],
            "dropped_before": dropped,
            "duplicate": [False] + [a == b for a, b in zip(hashes, hashes[1:], strict=False)],
        },
        schema=FRAMES.schema,
    )
    errors = FRAMES.errors(table)
    if errors:
        raise ValueError("; ".join(errors))
    return table
