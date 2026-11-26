"""Floor functions on synthetic cameras (docs/COURT.md)."""

import numpy as np
import pytest

from dinkdata.court.floor import (
    court_lines_image,
    court_to_image,
    feet_per_pixel,
    image_to_court,
)
from dinkdata.court.keypoints import COURT_LINE_ENDS, KEYPOINTS, KeypointName
from tests.court.cameras import BARREL, HEIGHT, SETUPS, WIDTH, calibration, looking_at

VIDEO = (WIDTH, HEIGHT)


def level_camera():
    """3 ft up at (10, 60), looking level along -y, f = 1000 px, no distortion.

    Its rotation turns court axes into camera axes: x stays x, the floor-down z axis becomes
    the image's down axis, and -y becomes the view direction. That is -90 degrees about x.
    The translation is -R @ (10, 60, -3).
    """
    return calibration((-np.pi / 2, 0.0, 0.0), (-10.0, 3.0, 60.0))


def test_points_with_a_height_project_to_the_expected_pixels():
    names: list[KeypointName] = ["net_top_left", "net_top_centre", "net_top_right"]
    points = np.array([KEYPOINTS[n] for n in names])
    pixels = court_to_image(level_camera(), points, video_size=VIDEO)
    # Each net top is 38 ft in front of the camera. The centre top is 1/6 ft below the lens.
    expected = [
        (960 - 1000 * 10 / 38, 540),
        (960, 540 + 1000 * (1 / 6) / 38),
        (960 + 1000 * 10 / 38, 540),
    ]
    np.testing.assert_allclose(pixels, expected, atol=1e-6)


def test_floor_points_need_no_height():
    pixels = court_to_image(level_camera(), np.array([[10.0, 44.0], [0.0, 44.0]]), video_size=VIDEO)
    # 16 ft in front of the camera and 3 ft below it.
    np.testing.assert_allclose(
        pixels, [(960, 540 + 3000 / 16), (960 - 10000 / 16, 540 + 3000 / 16)]
    )
    with_height = court_to_image(
        level_camera(), np.array([[10.0, 44.0, 0.0], [0.0, 44.0, 0.0]]), video_size=VIDEO
    )
    np.testing.assert_allclose(with_height, pixels)


def test_a_point_behind_the_camera_is_nan():
    pixels = court_to_image(level_camera(), np.array([[10.0, 70.0]]), video_size=VIDEO)
    assert np.isnan(pixels).all()


def test_a_size_mismatch_raises():
    with pytest.raises(ValueError, match="1280x720"):
        court_to_image(level_camera(), np.array([[10.0, 44.0]]), video_size=(1280, 720))


def synthetic(setup: str, lens: str):
    return looking_at(**SETUPS[setup], **(BARREL if lens == "barrel" else {}))


def floor_grid() -> np.ndarray:
    """The court and 10 ft beyond its lines on every side, every 2 ft."""
    xs, ys = np.meshgrid(np.arange(-10, 31, 2.0), np.arange(-10, 55, 2.0))
    return np.column_stack([xs.ravel(), ys.ravel()])


def in_frame(pixels: np.ndarray) -> np.ndarray:
    return (
        np.isfinite(pixels).all(axis=1)
        & (pixels[:, 0] >= 0)
        & (pixels[:, 0] <= WIDTH)
        & (pixels[:, 1] >= 0)
        & (pixels[:, 1] <= HEIGHT)
    )


@pytest.mark.parametrize("lens", ["pinhole", "barrel"])
@pytest.mark.parametrize("setup", ["dtl_low", "dtl_high", "diagonal"])
def test_floor_points_round_trip(setup, lens):
    camera = synthetic(setup, lens)
    floor = floor_grid()
    pixels = court_to_image(camera, floor, video_size=VIDEO)
    seen = in_frame(pixels)
    assert seen.sum() > 50, "the synthetic camera should see much of the court"
    back = image_to_court(camera, pixels[seen], video_size=VIDEO)
    np.testing.assert_allclose(back, floor[seen], atol=1e-6)


def test_the_barrel_lens_moves_pixels():
    floor = np.array([[0.0, 44.0]])
    plain = court_to_image(synthetic("dtl_low", "pinhole"), floor, video_size=VIDEO)
    bent = court_to_image(synthetic("dtl_low", "barrel"), floor, video_size=VIDEO)
    assert np.abs(plain - bent).max() > 50


@pytest.mark.parametrize("lens", ["pinhole", "barrel"])
def test_pixels_at_or_above_the_horizon_are_nan(lens):
    camera = synthetic("dtl_high", lens)
    # The camera is at (10, 56), 15 ft up. A point far ahead at its own height sits on the
    # horizon, and one higher sits above it. A point far ahead on the floor sits just below.
    ahead = np.array([[10.0, -400.0, 15.0], [10.0, -400.0, 30.0], [10.0, -400.0, 0.0]])
    pixels = court_to_image(camera, ahead, video_size=VIDEO)
    assert np.isfinite(pixels).all()
    court = image_to_court(camera, pixels, video_size=VIDEO)
    assert np.isnan(court[1]).all()
    np.testing.assert_allclose(court[2], [10.0, -400.0], atol=1e-3)
    # The horizon row itself: nudge it up by a hundredth of a pixel to stay off the boundary.
    horizon = image_to_court(camera, pixels[:1] - [0, 0.01], video_size=VIDEO)
    assert np.isnan(horizon).all()


def test_image_to_court_rejects_a_size_mismatch():
    with pytest.raises(ValueError, match="1280x720"):
        image_to_court(
            synthetic("dtl_low", "pinhole"), np.array([[960.0, 900.0]]), video_size=(1280, 720)
        )


def test_a_pixel_past_a_folding_lens_edge_is_nan():
    # With k1 = -0.3 and no k2, the distorted radius peaks at 0.70 focal lengths, so the
    # image corner, 1.1 focal lengths from the centre, is past the fold.
    camera = looking_at(**SETUPS["dtl_low"], k1=-0.3)
    corner = image_to_court(camera, np.array([[0.0, HEIGHT]]), video_size=VIDEO)
    assert np.isnan(corner).all()


def chord_distance(polyline: np.ndarray) -> np.ndarray:
    """Each point's distance from the straight line through the polyline's ends."""
    a, b = polyline[0], polyline[-1]
    d = (b - a) / np.linalg.norm(b - a)
    rel = polyline - a
    return np.abs(rel[:, 0] * d[1] - rel[:, 1] * d[0])


@pytest.mark.parametrize("lens", ["pinhole", "barrel"])
def test_court_lines_lie_on_the_projected_lines(lens):
    camera = synthetic("dtl_high", lens)
    lines = court_lines_image(camera, video_size=VIDEO)
    assert set(lines) == set(COURT_LINE_ENDS)
    for name, polyline in lines.items():
        (x0, y0), (x1, y1) = COURT_LINE_ENDS[name]
        ends = court_to_image(camera, np.array([[x0, y0], [x1, y1]]), video_size=VIDEO)
        np.testing.assert_allclose(polyline[[0, -1]], ends, atol=1e-6, err_msg=name)
        court = image_to_court(camera, polyline, video_size=VIDEO)
        # Every sample maps back onto the court line it came from.
        if x0 == x1:
            np.testing.assert_allclose(court[:, 0], x0, atol=1e-6, err_msg=name)
        else:
            np.testing.assert_allclose(court[:, 1], y0, atol=1e-6, err_msg=name)


def test_a_distorted_camera_bends_the_lines():
    straight = court_lines_image(synthetic("dtl_high", "pinhole"), video_size=VIDEO)
    bent = court_lines_image(synthetic("dtl_high", "barrel"), video_size=VIDEO)
    assert chord_distance(straight["near_baseline"]).max() < 1e-6
    assert chord_distance(bent["near_baseline"]).max() > 5


@pytest.mark.parametrize("lens", ["pinhole", "barrel"])
@pytest.mark.parametrize("setup", ["dtl_low", "dtl_high", "diagonal"])
def test_feet_per_pixel_matches_a_finite_difference(setup, lens):
    camera = synthetic(setup, lens)
    points = np.array([[2.0, 40.0], [10.0, 30.0], [18.0, 20.0], [10.0, 3.0]])
    got = feet_per_pixel(camera, points, video_size=VIDEO)
    pixels = court_to_image(camera, points, video_size=VIDEO)
    step = 0.01
    for point_px, value in zip(pixels, got, strict=True):
        columns = [
            (
                image_to_court(camera, (point_px + d)[None], video_size=VIDEO)
                - image_to_court(camera, (point_px - d)[None], video_size=VIDEO)
            )[0]
            / (2 * step)
            for d in (np.array([step, 0.0]), np.array([0.0, step]))
        ]
        jacobian = np.column_stack(columns)
        # The floor distance of one pixel in the direction where a pixel covers the most floor.
        assert value == pytest.approx(np.linalg.norm(jacobian, 2), rel=1e-4)


def test_feet_per_pixel_grows_with_distance():
    near, far = feet_per_pixel(
        synthetic("dtl_low", "barrel"), np.array([[10.0, 40.0], [10.0, 2.0]]), video_size=VIDEO
    )
    assert far > 3 * near


def test_feet_per_pixel_is_nan_where_the_camera_cannot_see():
    value = feet_per_pixel(level_camera(), np.array([[10.0, 70.0]]), video_size=VIDEO)
    assert np.isnan(value).all()
