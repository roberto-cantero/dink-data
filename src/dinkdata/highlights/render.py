"""The on-request MP4 renderer: FFmpeg cuts, marks and joins a reel's clips (DESIGN 3.3, 6.12).

Every cut re-encodes, because a cut without re-encoding can only start on a keyframe. Each clip
is cut and re-encoded on its own, the opening title card is rendered the same way from a still
image, and the pieces are then joined with another re-encode so a timestamp glitch at a join
can't carry into the output. The marker is a small circle "under the player's feet"; M0 has no
tracking, so a clip gets one only when the caller supplies its pixel position by hand.

Calls pass their arguments as a list, with no shell, and keep ffmpeg's message for errors
(`dinkdata.video.ffmpeg`, the same convention intake uses).
"""

import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import cv2
import numpy as np

from dinkdata.contracts.highlights import Clip, Reel
from dinkdata.video.ffmpeg import FfmpegError, missing_tools

TITLE_SECONDS = 2.5
OUTPUT_FRAME_RATE = 30
CODEC_ARGS = ("-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an")
MARKER_RADIUS = 10
MARKER_SIZE = MARKER_RADIUS * 2 + 6
MARKER_COLOR = (0, 230, 255, 255)  # BGRA, matches the court tracking marker elsewhere


class RenderError(ValueError):
    """A reel can't be rendered: a bad clip, marker or title card."""


@dataclass(frozen=True)
class TitleCard:
    """What the reel's opening card shows (DESIGN 3.3). Never the score (ADR 0019)."""

    photo_crop: Path | None
    game_number: int
    date: date


def _run(args: list[str]) -> None:
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise FfmpegError("ffmpeg", result.stderr)


def _probe_size(video: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(video),
        ],
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip
    if result.returncode != 0:
        raise FfmpegError("ffprobe", result.stderr)
    streams = json.loads(result.stdout).get("streams") or []
    if not streams:
        raise FfmpegError("ffprobe", "the file has no video stream")
    return int(streams[0]["width"]), int(streams[0]["height"])


def _draw_title_card(card: TitleCard, size: tuple[int, int]) -> np.ndarray:
    width, height = size
    image = np.zeros((height, width, 3), dtype=np.uint8)
    if card.photo_crop is not None:
        photo = cv2.imread(str(card.photo_crop))
        if photo is None:
            raise RenderError(f"can't read photo crop {card.photo_crop}")
        crop_h = int(height * 0.6)
        crop_w = max(1, int(crop_h * photo.shape[1] / photo.shape[0]))
        photo = cv2.resize(photo, (crop_w, crop_h))
        x, y = (width - crop_w) // 2, int(height * 0.08)
        image[y : y + crop_h, x : x + crop_w] = photo
    text = f"Game {card.game_number}  -  {card.date.isoformat()}"
    (text_w, text_h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
    origin = ((width - text_w) // 2, height - max(text_h, int(height * 0.08)))
    cv2.putText(image, text, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    return image


def _write_marker_png(work: Path) -> Path:
    image = np.zeros((MARKER_SIZE, MARKER_SIZE, 4), dtype=np.uint8)
    center = MARKER_SIZE // 2
    cv2.circle(image, (center, center), MARKER_RADIUS, MARKER_COLOR, 3, cv2.LINE_AA)
    png = work / "marker.png"
    if not cv2.imwrite(str(png), image):
        raise RenderError(f"couldn't write {png}")
    return png


def _render_title_card(card: TitleCard, size: tuple[int, int], work: Path) -> Path:
    png = work / "title.png"
    if not cv2.imwrite(str(png), _draw_title_card(card, size)):
        raise RenderError(f"couldn't write {png}")
    out = work / "title.mp4"
    _run(
        [
            "-loop", "1", "-i", str(png),
            "-t", f"{TITLE_SECONDS:.3f}",
            "-vf", f"fps={OUTPUT_FRAME_RATE}",
            *CODEC_ARGS,
            str(out),
        ]
    )  # fmt: skip
    png.unlink()
    return out


def _render_clip(
    video: Path, clip: Clip, marker: tuple[float, float] | None, marker_png: Path | None, work: Path
) -> Path:
    out = work / f"{clip.id}.mp4"
    duration = clip.end_t - clip.start_t
    args = ["-ss", f"{clip.start_t:.3f}", "-i", str(video), "-t", f"{duration:.3f}"]
    if marker is not None and marker_png is not None:
        x, y = marker[0] - MARKER_SIZE / 2, marker[1] - MARKER_SIZE / 2
        args += ["-loop", "1", "-i", str(marker_png)]
        args += [
            "-filter_complex",
            f"[0:v]setpts=PTS-STARTPTS,fps={OUTPUT_FRAME_RATE}[base];"
            f"[base][1:v]overlay={x:.1f}:{y:.1f}:shortest=1[v]",
            "-map", "[v]",
        ]  # fmt: skip
    else:
        args += ["-vf", f"setpts=PTS-STARTPTS,fps={OUTPUT_FRAME_RATE}"]
    args += [*CODEC_ARGS, str(out)]
    _run(args)
    return out


def _concat(parts: list[Path], out: Path) -> None:
    list_file = parts[0].parent / "concat.txt"
    list_file.write_text("".join(f"file '{p.name}'\n" for p in parts))
    _run(["-f", "concat", "-safe", "0", "-i", str(list_file), *CODEC_ARGS, str(out)])
    list_file.unlink()


def render_reel(
    video: Path,
    reel: Reel,
    card: TitleCard,
    out: Path,
    *,
    markers: Mapping[str, tuple[float, float]] | None = None,
    work_dir: Path | None = None,
) -> Path:
    """Render `reel`'s clips from `video` into `out`, an MP4 that opens with the title card.

    `markers`, keyed by clip id, places a small circle at that pixel position in every frame of
    that clip. A clip not in `markers` gets no marker: M0 has no tracking to draw one from.
    """
    missing = missing_tools()
    if missing:
        raise FfmpegError("ffmpeg", f"missing {', '.join(missing)} (brew install ffmpeg)")
    markers = markers or {}

    size = _probe_size(video)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = work_dir or out.parent / f".{out.stem}.parts"
    work.mkdir(parents=True, exist_ok=True)
    try:
        marker_png = _write_marker_png(work) if markers else None
        parts = [_render_title_card(card, size, work)]
        for clip in reel.clips:
            parts.append(_render_clip(video, clip, markers.get(clip.id), marker_png, work))
        _concat(parts, out)
        return out
    finally:
        for leftover in work.glob("*"):
            leftover.unlink()
        work.rmdir()
