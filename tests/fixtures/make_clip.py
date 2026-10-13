"""Generate a small synthetic court clip for tests (no real footage in the repo).

The court is drawn top-down at 3.5 px/ft, centred in a 320x180 frame, so it
matches the homography in `court.json` next to this file. A ball moves from the
near baseline toward the net.

Usage: uv run python tests/fixtures/make_clip.py out/clip.mp4
"""

import sys
from pathlib import Path

import cv2
import numpy as np

WIDTH, HEIGHT = 320, 180
PX_PER_FT = 3.5
ORIGIN = (125.0, 13.0)  # image px of the court origin (far-left baseline corner)


def court_to_px(x_ft: float, y_ft: float) -> tuple[int, int]:
    return round(ORIGIN[0] + x_ft * PX_PER_FT), round(ORIGIN[1] + y_ft * PX_PER_FT)


def make_clip(path: Path, seconds: float = 2.0, fps: int = 30) -> Path:
    """Write the clip to `path` and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"mp4v"), fps, (WIDTH, HEIGHT))
    n_frames = round(seconds * fps)
    for i in range(n_frames):
        frame = np.full((HEIGHT, WIDTH, 3), (60, 120, 60), dtype=np.uint8)
        white = (255, 255, 255)
        cv2.rectangle(frame, court_to_px(0, 0), court_to_px(20, 44), white, 1)
        for y in (15, 29):  # kitchen lines
            cv2.line(frame, court_to_px(0, y), court_to_px(20, y), white, 1)
        cv2.line(frame, court_to_px(0, 22), court_to_px(20, 22), (200, 200, 200), 2)  # net
        t = i / max(n_frames - 1, 1)
        cv2.circle(frame, court_to_px(10 + 4 * t, 40 - 25 * t), 2, (0, 230, 255), -1)
        writer.write(frame)
    writer.release()
    return path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(make_clip(Path(sys.argv[1])))
