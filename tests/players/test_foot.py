"""The foot point: ankles, then the box bottom, then the hips when the frame cuts the feet off."""

import numpy as np
import pytest

from dinkdata.players.foot import LEG_TO_TORSO, foot_point

HEIGHT = 1080


def skeleton(shoulder_y=400.0, hip_y=550.0, ankle_y=850.0, conf=0.9, ankle_conf=0.9):
    """17 COCO keypoints of a person standing at x 300 to 340."""
    kp = np.zeros((17, 3), dtype=np.float32)
    kp[5] = (300, shoulder_y, conf)
    kp[6] = (340, shoulder_y, conf)
    kp[11] = (305, hip_y, conf)
    kp[12] = (335, hip_y, conf)
    kp[15] = (302, ankle_y, ankle_conf)
    kp[16] = (342, ankle_y + 4, ankle_conf * 0.8)
    return kp


def test_the_ankle_midpoint_when_both_ankles_are_found():
    foot = foot_point((280, 350, 360, 870), skeleton(), det_conf=0.95, frame_height=HEIGHT)
    assert foot is not None
    assert (foot.x, foot.y) == pytest.approx((322, 852))
    assert foot.conf == pytest.approx(0.72)
    assert not foot.estimated
    assert foot.source == "ankles"


def test_the_box_bottom_when_an_ankle_is_missing():
    kp = skeleton(ankle_conf=0.1)
    foot = foot_point((280, 350, 360, 870), kp, det_conf=0.8, frame_height=HEIGHT)
    assert foot is not None
    assert (foot.x, foot.y) == pytest.approx((320, 870))
    assert foot.conf == pytest.approx(0.8)
    assert not foot.estimated
    assert foot.source == "box"


def test_the_hips_when_the_box_touches_the_frame_bottom():
    """The pose model still guesses ankles at the frame edge, so they are ignored."""
    kp = skeleton(shoulder_y=700, hip_y=900, ankle_y=1075)
    foot = foot_point((280, 650, 360, HEIGHT), kp, det_conf=0.9, frame_height=HEIGHT)
    assert foot is not None
    assert foot.x == pytest.approx(320)
    assert foot.y == pytest.approx(900 + LEG_TO_TORSO * 200)
    assert foot.y > HEIGHT
    assert foot.conf == pytest.approx(0.45)
    assert foot.estimated
    assert foot.source == "hips"


def test_no_foot_point_when_the_frame_cuts_off_the_hips_too():
    kp = skeleton(shoulder_y=900, hip_y=1078)
    kp[11, 2] = kp[12, 2] = 0.05
    assert foot_point((280, 850, 360, HEIGHT), kp, det_conf=0.9, frame_height=HEIGHT) is None


def test_no_foot_point_from_hips_without_shoulders():
    kp = skeleton(shoulder_y=700, hip_y=900)
    kp[5, 2] = kp[6, 2] = 0.0
    assert foot_point((280, 650, 360, HEIGHT), kp, det_conf=0.9, frame_height=HEIGHT) is None
