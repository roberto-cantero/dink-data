"""Court zones in feet (docs/COURT.md zone table)."""

import pytest

from dinkdata.court.zones import (
    depth_bucket,
    feet_to_baseline,
    half,
    in_court,
    in_service_court,
    other_half,
)


def test_half_splits_at_the_net():
    assert half((10, 5)) == "far"
    assert half((10, 40)) == "near"
    assert half((10, 22)) is None
    assert other_half("far") == "near"
    assert other_half("near") == "far"


@pytest.mark.parametrize(
    ("point", "inside"),
    [
        ((0, 0), True),
        ((20, 44), True),
        ((10, 22), True),
        ((-0.1, 10), False),
        ((20.1, 10), False),
        ((10, 44.1), False),
        ((10, -0.1), False),
    ],
)
def test_in_court_counts_the_lines_as_in(point, inside):
    assert in_court(point) is inside


@pytest.mark.parametrize(
    ("point", "side", "inside"),
    [
        # A far-half bounce comes from a server at the near end, whose right is the camera's
        # right, so a serve from the right lands left of the centre line.
        ((5, 8), "right", True),
        ((15, 8), "right", False),
        ((15, 8), "left", True),
        ((5, 8), "left", False),
        # A near-half bounce comes from a server at the far end, facing the camera.
        ((15, 36), "right", True),
        ((5, 36), "right", False),
        ((5, 36), "left", True),
        # The centre line, sidelines and baseline are in.
        ((10, 8), "right", True),
        ((10, 8), "left", True),
        ((0, 0), "right", True),
        ((20, 44), "right", True),
        # The kitchen line is a fault, and so is the kitchen.
        ((5, 15), "right", False),
        ((15, 29), "right", False),
        ((5, 18), "right", False),
        # Long or wide is out.
        ((5, -0.5), "right", False),
        ((-0.5, 8), "right", False),
        # The net line is in neither half.
        ((5, 22), "right", False),
    ],
)
def test_in_service_court(point, side, inside):
    assert in_service_court(point, side) is inside


def test_feet_to_baseline_measures_to_the_baseline_of_the_bounces_half():
    assert feet_to_baseline((5, 3)) == 3
    assert feet_to_baseline((5, 40)) == 4


@pytest.mark.parametrize(
    ("feet", "bucket"),
    [(0, "deep"), (5, "deep"), (5.1, "medium"), (10, "medium"), (10.1, "short"), (14, "short")],
)
def test_depth_buckets(feet, bucket):
    assert depth_bucket(feet) == bucket
