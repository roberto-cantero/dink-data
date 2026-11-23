"""The named keypoints and court lines match the tables in docs/COURT.md."""

import pytest

from dinkdata.court.keypoints import COURT_LINES, KEYPOINTS, KeypointName


def test_keypoints_match_court_md():
    # (x, y, height) in feet, copied by hand from the keypoint table in docs/COURT.md.
    expected: dict[KeypointName, tuple[float, float, float]] = {
        "far_left_corner": (0, 0, 0),
        "far_right_corner": (20, 0, 0),
        "near_right_corner": (20, 44, 0),
        "near_left_corner": (0, 44, 0),
        "far_kitchen_left": (0, 15, 0),
        "far_kitchen_right": (20, 15, 0),
        "near_kitchen_right": (20, 29, 0),
        "near_kitchen_left": (0, 29, 0),
        "far_kitchen_centre": (10, 15, 0),
        "near_kitchen_centre": (10, 29, 0),
        "far_baseline_centre": (10, 0, 0),
        "near_baseline_centre": (10, 44, 0),
        "net_top_left": (0, 22, 3),
        "net_top_centre": (10, 22, 2.83),
        "net_top_right": (20, 22, 3),
    }
    assert set(KEYPOINTS) == set(expected)
    for name, point in expected.items():
        assert KEYPOINTS[name] == pytest.approx(point, abs=0.005), name


def test_court_lines_match_court_md():
    # (from, to) in feet, copied by hand from the court line table in docs/COURT.md.
    expected = {
        "far_baseline": ((0, 0), (20, 0)),
        "near_baseline": ((0, 44), (20, 44)),
        "left_sideline": ((0, 0), (0, 44)),
        "right_sideline": ((20, 0), (20, 44)),
        "far_kitchen_line": ((0, 15), (20, 15)),
        "near_kitchen_line": ((0, 29), (20, 29)),
        "far_centre_line": ((10, 0), (10, 15)),
        "near_centre_line": ((10, 29), (10, 44)),
    }
    assert expected == COURT_LINES
