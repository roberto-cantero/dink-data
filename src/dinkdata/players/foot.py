"""A player's foot point in the image, the point the floor mapping places on the court (DESIGN
6.6 step 3).

The foot point is the midpoint of the ankles, or the bottom of the box when an ankle isn't
found. Near players are often cut off by the bottom of the frame. Then the pose model still
guesses ankles at the frame edge, so the foot point comes from the hips instead: the leg runs
below the hips about `LEG_TO_TORSO` times the shoulder-to-hip length. That guess gets a lower
confidence and `estimated` is true.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

L_SHOULDER, R_SHOULDER, L_HIP, R_HIP, L_ANKLE, R_ANKLE = 5, 6, 11, 12, 15, 16
"""COCO keypoint indices."""

MIN_KEYPOINT_CONF = 0.3
"""A keypoint below this confidence counts as not found."""

BOTTOM_EDGE = 0.005
"""A box whose bottom is within this share of the frame height of the bottom edge is cut off."""

LEG_TO_TORSO = 1.7
"""Hip-to-floor height over shoulder-to-hip length. Standing adults are about 0.53 and 0.29 of
their height (Drillis and Contini, 1966), so 1.8, and a ready stance with bent knees is lower."""

HIP_CONF_SCALE = 0.5
"""A foot point from the hips gets this share of the hips' confidence."""


Box = Sequence[float] | np.ndarray
"""x1, y1, x2, y2 in pixels."""


@dataclass(frozen=True)
class FootPoint:
    x: float
    y: float
    conf: float
    estimated: bool
    """True when the point came from the hips."""
    source: Literal["ankles", "box", "hips"]


def foot_point(
    box: Box, keypoints: np.ndarray, det_conf: float, frame_height: int
) -> FootPoint | None:
    """The foot point of one person, or None when the frame cuts off the hips too.

    `box` is x1, y1, x2, y2 in pixels and `keypoints` is 17 x (x, y, conf) in pixels.
    """
    x1, _, x2, y2 = (float(v) for v in box)
    if y2 >= frame_height * (1 - BOTTOM_EDGE):
        return _from_hips(keypoints)
    ankles = keypoints[[L_ANKLE, R_ANKLE]]
    if (ankles[:, 2] >= MIN_KEYPOINT_CONF).all():
        x, y = ankles[:, :2].mean(axis=0)
        return FootPoint(float(x), float(y), float(ankles[:, 2].min()), False, "ankles")
    return FootPoint((x1 + x2) / 2, y2, float(det_conf), False, "box")


def _from_hips(keypoints: np.ndarray) -> FootPoint | None:
    hips = keypoints[[L_HIP, R_HIP]]
    shoulders = keypoints[[L_SHOULDER, R_SHOULDER]]
    if (hips[:, 2] < MIN_KEYPOINT_CONF).any() or (shoulders[:, 2] < MIN_KEYPOINT_CONF).any():
        return None
    hip = hips[:, :2].mean(axis=0)
    torso = hip[1] - shoulders[:, 1].mean()
    conf = HIP_CONF_SCALE * float(hips[:, 2].min())
    return FootPoint(float(hip[0]), float(hip[1] + LEG_TO_TORSO * torso), conf, True, "hips")
