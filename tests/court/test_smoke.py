import numpy as np
import pytest

import dinkdata.court


def test_imports():
    assert dinkdata.court.__doc__


def test_fixture_homography_maps_corners_to_court(court_json):
    H = np.array(court_json["homography"])
    for point in court_json["keypoints"].values():
        u, v = point["image_xy"]
        x, y, w = H @ np.array([u, v, 1.0])
        assert (x / w, y / w) == pytest.approx(tuple(point["court_xy"]), abs=1e-6)
