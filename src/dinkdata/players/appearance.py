"""Colour features of a player's clothes, for telling partners apart (DESIGN 6.6 step 2).

The shirt and the shorts each get an HSV histogram. The keypoints place them: the shirt runs
from the shoulders to the hips, the shorts from the hips to the knees. Without keypoints they
fall back to fixed shares of the box. Grey, white and black clothes have no reliable hue, so
the histogram bins value and saturation as well as hue.
"""

import cv2
import numpy as np

from dinkdata.players.foot import L_HIP, L_SHOULDER, MIN_KEYPOINT_CONF, R_HIP, R_SHOULDER, Box

L_KNEE, R_KNEE = 13, 14
BINS = (8, 3, 3)
"""Hue, saturation and value bins of each region's histogram."""

SHIRT_SHARE = (0.2, 0.5)
SHORTS_SHARE = (0.5, 0.72)
"""Rows of the box, top to bottom, used when the keypoints are missing."""

WIDTH_SHARE = 0.6
"""The middle share of the region's width that is kept, to leave out arms and background."""

THIGH_TO_TORSO = 0.7
"""Hip-to-knee over shoulder-to-hip length, for the shorts when the knees are missing."""

Region = tuple[float, float, float, float]


def body_regions(box: Box, keypoints: np.ndarray) -> tuple[Region, Region]:
    """The shirt and shorts regions, each x1, y1, x2, y2 in pixels."""
    x1, y1, x2, y2 = (float(v) for v in box)
    found = keypoints[:, 2] >= MIN_KEYPOINT_CONF
    height = y2 - y1

    def rows(share: tuple[float, float]) -> tuple[float, float]:
        return y1 + share[0] * height, y1 + share[1] * height

    if found[[L_SHOULDER, R_SHOULDER, L_HIP, R_HIP]].all():
        top = keypoints[[L_SHOULDER, R_SHOULDER], 1].mean()
        hip = keypoints[[L_HIP, R_HIP], 1].mean()
        shirt_rows = (top, hip)
        left = keypoints[[L_SHOULDER, R_SHOULDER, L_HIP, R_HIP], 0].min()
        right = keypoints[[L_SHOULDER, R_SHOULDER, L_HIP, R_HIP], 0].max()
        if found[[L_KNEE, R_KNEE]].all():
            shorts_rows = (hip, keypoints[[L_KNEE, R_KNEE], 1].mean())
        else:
            shorts_rows = (hip, hip + (hip - top) * THIGH_TO_TORSO)
    else:
        shirt_rows, shorts_rows = rows(SHIRT_SHARE), rows(SHORTS_SHARE)
        left, right = x1, x2

    centre, half = (left + right) / 2, (right - left) * WIDTH_SHARE / 2
    xa, xb = float(centre - half), float(centre + half)
    shirt = (xa, float(shirt_rows[0]), xb, float(shirt_rows[1]))
    shorts = (xa, float(shorts_rows[0]), xb, float(shorts_rows[1]))
    return shirt, shorts


def _histogram(hsv: np.ndarray, region: Region) -> np.ndarray:
    h, w = hsv.shape[:2]
    x1, y1, x2, y2 = region
    xa, xb = int(np.clip(x1, 0, w - 1)), int(np.clip(np.ceil(x2), 1, w))
    ya, yb = int(np.clip(y1, 0, h - 1)), int(np.clip(np.ceil(y2), 1, h))
    patch = hsv[ya : max(yb, ya + 1), xa : max(xb, xa + 1)]
    hist = cv2.calcHist([patch], [0, 1, 2], None, list(BINS), [0, 180, 0, 256, 0, 256])
    hist = hist.flatten()
    total = hist.sum()
    return hist / total if total > 0 else hist


def colour_feature(image: np.ndarray, box: Box, keypoints: np.ndarray) -> np.ndarray:
    """The unit-length colour feature of one person in an RGB image."""
    shirt, shorts = body_regions(box, keypoints)
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    feature = np.concatenate([_histogram(hsv, shirt), _histogram(hsv, shorts)])
    # The square root turns histogram overlap into cosine similarity (the Hellinger kernel).
    feature = np.sqrt(feature)
    norm = np.linalg.norm(feature)
    return (feature / norm if norm > 0 else feature).astype(np.float32)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na > 0 and nb > 0 else 0.0
