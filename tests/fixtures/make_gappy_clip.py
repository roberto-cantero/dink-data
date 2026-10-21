"""A tiny MP4 with dropped frames, made with PyAV, for the video reader's tests (no real footage).

Each picture carries its camera frame number as a row of black and white blocks, so a test can
tell which frame it got back. Some camera frames are cut, which leaves gaps in the timestamps
like frames a camera dropped. A 12-frame GOP with B-frames makes decode order differ from
display order, and frames 11 and 12 are decoded after the keyframe at 13 although they are
shown before it. So random access has to seek to a keyframe and decode forward.

Usage: uv run python tests/fixtures/make_gappy_clip.py out/gappy.mp4
"""

import sys
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

# 512 ticks of 1/15360 s a frame, as ffmpeg writes a 30 fps MP4.
TIME_BASE = Fraction(1, 15360)
TICKS = 512
WIDTH, HEIGHT = 64, 48
BLOCK = 8  # one bit of the frame number per 8x8 block along the top row
CAMERA_FRAMES = 60
CUT = (10, 30, 31, 32)  # one dropped frame before a B-frame, then three in a row
KEPT = [n for n in range(CAMERA_FRAMES) if n not in CUT]
"""The camera frame number of every decoded frame, in display order."""


def camera_t(number: int) -> float:
    """The time of a camera frame, in seconds from the first frame."""
    return float(number * TICKS * TIME_BASE)


def paint(number: int) -> np.ndarray:
    image = np.full((HEIGHT, WIDTH, 3), 128, dtype=np.uint8)
    for bit in range(WIDTH // BLOCK):
        image[:BLOCK, bit * BLOCK : (bit + 1) * BLOCK] = 255 if (number >> bit) & 1 else 0
    return image


def read_number(image: np.ndarray) -> int:
    """The camera frame number painted into an RGB picture."""
    blocks = image[:BLOCK, : WIDTH // BLOCK * BLOCK].reshape(BLOCK, WIDTH // BLOCK, BLOCK, 3)
    bits = blocks.mean(axis=(0, 2, 3)) > 128
    return sum(1 << bit for bit, on in enumerate(bits) if on)


def make_gappy_clip(path: Path) -> Path:
    """Write the clip to `path` and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=30)
        stream.width, stream.height, stream.pix_fmt = WIDTH, HEIGHT, "yuv420p"
        stream.time_base = TIME_BASE
        stream.codec_context.time_base = TIME_BASE
        # No scene-cut keyframes, so keyframes fall every 12 frames.
        stream.options = {"g": "12", "bf": "2", "sc_threshold": "1000000000"}
        for number in KEPT:
            frame = av.VideoFrame.from_ndarray(paint(number), format="rgb24")
            frame.pts = number * TICKS
            frame.time_base = TIME_BASE
            out.mux(stream.encode(frame))
        out.mux(stream.encode())
    return path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(make_gappy_clip(Path(sys.argv[1])))
