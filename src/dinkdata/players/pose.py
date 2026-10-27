"""RTMPose pre- and post-processing (Jiang et al., 2023), without the model.

A person's box grows by `PADDING` and to the model's aspect ratio, and that region is resized
to the 192 x 256 input. The model gives each keypoint two 1-D classification vectors, SimCC,
over `SPLIT_RATIO` bins per input pixel. The arg-max of each gives the position, and the
smaller of the two maxima gives the score.
"""

import numpy as np

from dinkdata.players.foot import Box

INPUT_W, INPUT_H = 192, 256
PADDING = 1.25
SPLIT_RATIO = 2.0
MEAN = np.array([123.675, 116.28, 103.53], dtype=np.float32)
STD = np.array([58.395, 57.12, 57.375], dtype=np.float32)
"""ImageNet RGB normalisation, which RTMPose trains with."""


def box_to_centre_scale(box: Box) -> tuple[np.ndarray, np.ndarray]:
    """Centre and size, in pixels, of the image region the model sees for one box."""
    x1, y1, x2, y2 = (float(v) for v in box)
    centre = np.array([(x1 + x2) / 2, (y1 + y2) / 2])
    w, h = (x2 - x1) * PADDING, (y2 - y1) * PADDING
    aspect = INPUT_W / INPUT_H
    if w > h * aspect:
        h = w / aspect
    else:
        w = h * aspect
    return centre, np.array([w, h])


def to_input(points: np.ndarray, centre: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """Image pixels to input pixels."""
    size = np.array([INPUT_W, INPUT_H])
    return (points - (centre - scale / 2)) * size / scale


def from_input(points: np.ndarray, centre: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """Input pixels to image pixels."""
    size = np.array([INPUT_W, INPUT_H])
    return points * scale / size + centre - scale / 2


def warp_matrix(centre: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """The 2 x 3 affine matrix that maps the region to the input, for `cv2.warpAffine`."""
    sx, sy = INPUT_W / scale[0], INPUT_H / scale[1]
    ox, oy = centre - scale / 2
    return np.array([[sx, 0, -ox * sx], [0, sy, -oy * sy]], dtype=np.float32)


def decode_simcc(simcc_x: np.ndarray, simcc_y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Keypoints in input pixels (n x k x 2) and scores in [0, 1] (n x k)."""
    x = simcc_x.argmax(axis=-1)
    y = simcc_y.argmax(axis=-1)
    scores = np.minimum(simcc_x.max(axis=-1), simcc_y.max(axis=-1))
    locs = np.stack([x, y], axis=-1).astype(np.float64) / SPLIT_RATIO
    return locs, np.clip(scores, 0, 1)
