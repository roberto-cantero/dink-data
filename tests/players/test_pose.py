"""RTMPose pre- and post-processing: the box crop and the SimCC decode. The model test needs the
downloaded weights."""

import numpy as np
import pytest

from dinkdata.players.pose import (
    INPUT_H,
    INPUT_W,
    SPLIT_RATIO,
    box_to_centre_scale,
    decode_simcc,
    from_input,
    to_input,
)


def test_the_box_grows_to_the_model_aspect_and_padding():
    centre, scale = box_to_centre_scale((100, 200, 140, 400))
    assert centre == pytest.approx((120, 300))
    assert scale[1] == pytest.approx(200 * 1.25)
    assert scale[0] / scale[1] == pytest.approx(INPUT_W / INPUT_H)


def test_a_wide_box_keeps_its_width():
    _, scale = box_to_centre_scale((0, 0, 400, 100))
    assert scale[0] == pytest.approx(500)
    assert scale[0] / scale[1] == pytest.approx(INPUT_W / INPUT_H)


def test_points_go_to_the_input_and_back():
    centre, scale = box_to_centre_scale((100, 200, 140, 400))
    points = np.array([[120.0, 300.0], [101.0, 210.0], [139.0, 390.0]])
    there = to_input(points, centre, scale)
    assert there[0] == pytest.approx((INPUT_W / 2, INPUT_H / 2))
    assert from_input(there, centre, scale) == pytest.approx(points)


def test_simcc_peaks_become_input_pixels_and_scores():
    x = np.zeros((1, 2, int(INPUT_W * SPLIT_RATIO)), dtype=np.float32)
    y = np.zeros((1, 2, int(INPUT_H * SPLIT_RATIO)), dtype=np.float32)
    x[0, 0, 100], y[0, 0, 300] = 0.9, 0.7
    x[0, 1, 10], y[0, 1, 20] = 0.4, 0.8
    locs, scores = decode_simcc(x, y)
    assert locs[0].tolist() == [[50, 150], [5, 10]]
    assert scores[0] == pytest.approx([0.7, 0.4])


def test_scores_stay_between_0_and_1():
    x = np.full((1, 1, int(INPUT_W * SPLIT_RATIO)), -0.5, dtype=np.float32)
    y = np.full((1, 1, int(INPUT_H * SPLIT_RATIO)), 1.4, dtype=np.float32)
    _, scores = decode_simcc(x, y)
    assert scores[0, 0] == 0
    x[:] = 1.6
    _, scores = decode_simcc(x, y)
    assert scores[0, 0] == 1
