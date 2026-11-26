"""The floor functions run on the core install, without the `cv` extra."""

import subprocess
import sys
from pathlib import Path

SCRIPT = """
import importlib.abc
import sys

BLOCKED = {"cv2", "scipy", "torch", "torchvision", "av", "onnxruntime", "rfdetr"}


class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ImportError(f"{name} is in the cv extra")
        return None


sys.meta_path.insert(0, Block())

import numpy as np

from dinkdata.court.floor import (
    court_lines_image, court_to_image, feet_per_pixel, image_to_court, load_camera,
)
from tests.court.cameras import BARREL, HEIGHT, SETUPS, WIDTH, looking_at

camera = looking_at(**SETUPS["diagonal"], **BARREL)
video = (WIDTH, HEIGHT)
floor = np.array([[5.0, 30.0], [15.0, 10.0]])
pixels = court_to_image(camera, floor, video_size=video)
assert np.allclose(image_to_court(camera, pixels, video_size=video), floor)
assert np.isfinite(feet_per_pixel(camera, floor, video_size=video)).all()
assert len(court_lines_image(camera, video_size=video)) == 8
assert not BLOCKED & {name.split(".")[0] for name in sys.modules}
print("ok")
"""


def test_floor_functions_need_only_numpy():
    root = Path(__file__).parents[2]
    out = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=root, capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"
