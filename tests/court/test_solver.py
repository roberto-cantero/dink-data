"""The calibration solver on synthetic cameras (docs/COURT.md, ADR 0020). No real footage."""

import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from dinkdata.contracts.camera import CameraCalibration
from dinkdata.contracts.camera_clicks import CameraClicks
from dinkdata.court import solver
from dinkdata.court.floor import court_to_image, image_to_court, max_radius, rotation
from dinkdata.court.solver import (
    CameraBelowFloor,
    CameraBeyondNet,
    CollinearKeypoints,
    FitDidNotConverge,
    FoldingLens,
    HeldBackErrorUndefined,
    TooFewKeypoints,
    fold_radius_px,
    line_centre,
    solve,
)
from tests.court.cameras import BARREL, HEIGHT, SETUPS, WIDTH, Setup, looking_at
from tests.court.clicks import VIDEO, make_clicks

INCH = 1 / 12


SOLVER_SETUPS: dict[str, Setup] = {
    **SETUPS,
    # 6 ft behind the baseline rather than 10, so the near corners are out of frame.
    "dtl_low": Setup(**{**SETUPS["dtl_low"], "y": 50.0}),
}


def synthetic(setup: str) -> CameraCalibration:
    return looking_at(**SOLVER_SETUPS[setup], **BARREL)


def centre_of(camera: CameraCalibration) -> np.ndarray:
    return -rotation(camera.rotation).T @ np.asarray(camera.translation)


def angle_between_deg(a: CameraCalibration, b: CameraCalibration) -> float:
    rel = rotation(a.rotation) @ rotation(b.rotation).T
    return float(np.degrees(np.arccos(np.clip((np.trace(rel) - 1) / 2, -1, 1))))


def rename(clicks: CameraClicks, swap: tuple[str, str]) -> CameraClicks:
    """The same clicks with two words swapped in every name, as a confused labeller would."""
    a, b = swap

    def swapped(name: str) -> str:
        return name.replace(a, "\0").replace(b, a).replace("\0", b)

    record: dict[str, Any] = clicks.model_dump(by_alias=True, mode="json")
    for field in ("keypoints", "line_points", "net_tops"):
        record[field] = {swapped(k): v for k, v in record[field].items()}
    return CameraClicks.model_validate(record)


# The painted lines' centres


def test_line_centres_sit_1_inch_inside_the_boundaries():
    assert line_centre((0.0, 0.0)) == pytest.approx((INCH, INCH))
    assert line_centre((20.0, 44.0)) == pytest.approx((20 - INCH, 44 - INCH))
    # Each kitchen line lies inside its kitchen, so its centre moves toward the net.
    assert line_centre((0.0, 15.0)) == pytest.approx((INCH, 15 + INCH))
    assert line_centre((20.0, 29.0)) == pytest.approx((20 - INCH, 29 - INCH))
    # The centre line stays at x = 10. Only its ends move, with the line they meet.
    assert line_centre((10.0, 0.0)) == pytest.approx((10.0, INCH))
    assert line_centre((10.0, 29.0)) == pytest.approx((10.0, 29 - INCH))
    # The net tops stand above the sidelines' centres, at the net.
    assert line_centre((0.0, 22.0)) == pytest.approx((INCH, 22.0))


# Recovering a camera


@pytest.mark.parametrize("setup", ["dtl_low", "dtl_high", "diagonal"])
def test_recovers_each_setup_from_noisy_clicks(setup: str):
    truth = synthetic(setup)
    clicks = make_clicks(truth, noise_px=0.5, seed=1)
    if setup == "dtl_low":
        assert "near_left_corner" not in clicks.keypoints  # a partial court
        assert "near_right_corner" not in clicks.keypoints

    fit = solve(clicks, setup=truth.setup)
    got = fit.camera

    assert got.intrinsics.fx == pytest.approx(truth.intrinsics.fx, rel=0.02)
    assert got.intrinsics.fy == got.intrinsics.fx
    assert (got.intrinsics.cx, got.intrinsics.cy) == (WIDTH / 2, HEIGHT / 2)
    assert got.distortion.k1 == pytest.approx(truth.distortion.k1, abs=0.03)
    assert got.distortion.k2 == pytest.approx(truth.distortion.k2, abs=0.05)
    assert np.linalg.norm(centre_of(got) - centre_of(truth)) < 0.5
    assert angle_between_deg(got, truth) < 0.5
    # Pixel noise of 0.5 px gives a held-back error of about that size.
    assert 0.1 < got.reprojection_error_px < 2.0


def test_the_result_is_a_valid_camera_json_from_clicks():
    truth = synthetic("dtl_high")
    clicks = make_clicks(truth, overlay_rects=[(1700.0, 20.0, 1900.0, 80.0)])

    camera = solve(clicks, setup="dtl_high").camera

    again = CameraCalibration.model_validate_json(camera.model_dump_json(by_alias=True))
    assert again == camera
    assert camera.source == "clicks"
    assert (camera.camera_id, camera.version) == (clicks.camera_id, clicks.version)
    assert camera.setup == "dtl_high"
    assert camera.model is None
    assert (camera.image_size.width, camera.image_size.height) == (WIDTH, HEIGHT)
    assert camera.overlay_masks == [[(1700, 20), (1900, 20), (1900, 80), (1700, 80)]]


def test_constants_scale_with_the_image_size():
    """The same clicks at half the size give the same pose and half the pixel error."""
    clicks = make_clicks(synthetic("diagonal"), noise_px=1.0, seed=3)
    record = clicks.model_dump(by_alias=True, mode="json")
    record["image_size"] = {"width": WIDTH // 2, "height": HEIGHT // 2}
    for field in ("keypoints", "net_tops"):
        record[field] = {k: [v[0] / 2, v[1] / 2] for k, v in record[field].items()}
    record["line_points"] = {
        k: [[x / 2, y / 2] for x, y in v] for k, v in record["line_points"].items()
    }
    half = CameraClicks.model_validate(record)

    full_fit = solve(clicks, setup="diagonal").camera
    half_fit = solve(half, setup="diagonal").camera

    np.testing.assert_allclose(half_fit.rotation, full_fit.rotation, atol=1e-4)
    np.testing.assert_allclose(half_fit.translation, full_fit.translation, atol=1e-3)
    assert half_fit.intrinsics.fx == pytest.approx(full_fit.intrinsics.fx / 2, rel=1e-4)
    assert half_fit.reprojection_error_px == pytest.approx(
        full_fit.reprojection_error_px / 2, rel=1e-3
    )


# The held-back error


def test_the_held_back_error_is_the_mean_leave_one_out_error():
    truth = synthetic("dtl_high")
    clicks = make_clicks(truth)
    moved = clicks.model_copy(deep=True)
    x, y = moved.keypoints["far_kitchen_left"]
    moved.keypoints["far_kitchen_left"] = (x + 12.0, y)

    fit = solve(moved, setup="dtl_high")

    # Every other click is exact, so the refit without the moved click finds the true
    # camera, which misses that click by the 12 px it was moved.
    assert fit.held_back_px["far_kitchen_left"] == pytest.approx(12.0, abs=0.5)
    others = [e for name, e in fit.held_back_px.items() if name != "far_kitchen_left"]
    assert max(others) < 0.5
    assert set(fit.held_back_px) == set(clicks.keypoints)
    assert fit.camera.reprojection_error_px == pytest.approx(
        np.mean(list(fit.held_back_px.values()))
    )


FOUR = ("far_left_corner", "far_right_corner", "far_kitchen_left", "far_kitchen_right")


def test_four_keypoints_with_line_points_on_two_lines_have_a_held_back_error():
    clicks = make_clicks(
        synthetic("dtl_high"),
        noise_px=0.3,
        keypoints=FOUR,
        lines=("far_baseline", "left_sideline", "right_sideline"),
    )
    assert len(clicks.keypoints) == 4

    fit = solve(clicks, setup="dtl_high")

    assert set(fit.held_back_px) == set(FOUR)
    assert np.isfinite(fit.camera.reprojection_error_px)


def test_four_keypoints_without_line_points_are_refused_as_undefined():
    clicks = make_clicks(synthetic("dtl_high"), keypoints=FOUR, lines=())
    with pytest.raises(HeldBackErrorUndefined, match="line points on at least 2"):
        solve(clicks, setup="dtl_high")


def test_four_keypoints_with_one_line_are_refused_as_undefined():
    clicks = make_clicks(synthetic("dtl_high"), keypoints=FOUR, lines=("far_baseline",))
    with pytest.raises(HeldBackErrorUndefined):
        solve(clicks, setup="dtl_high")


# Refusals


def test_fewer_than_4_keypoints_are_refused():
    clicks = make_clicks(synthetic("dtl_high"), keypoints=FOUR[:3])
    with pytest.raises(TooFewKeypoints, match="3 floor keypoints"):
        solve(clicks, setup="dtl_high")


def test_three_keypoints_on_one_line_are_refused():
    clicks = make_clicks(
        synthetic("dtl_high"),
        keypoints=(
            "far_left_corner",
            "far_baseline_centre",
            "far_right_corner",
            "far_kitchen_left",
        ),
    )
    with pytest.raises(CollinearKeypoints, match="far_baseline_centre"):
        solve(clicks, setup="dtl_high")


def test_a_full_court_with_3_keypoints_per_baseline_is_accepted():
    """Three on a line only matter when no 4 keypoints are left in general position."""
    clicks = make_clicks(
        synthetic("dtl_high"),
        keypoints=(
            "far_left_corner",
            "far_baseline_centre",
            "far_right_corner",
            "far_kitchen_left",
            "far_kitchen_right",
        ),
    )
    solve(clicks, setup="dtl_high")


def test_swapped_left_and_right_names_are_refused():
    clicks = rename(make_clicks(synthetic("dtl_high")), ("left", "right"))
    with pytest.raises(CameraBelowFloor, match="swapped"):
        solve(clicks, setup="dtl_high")


def test_swapped_near_and_far_names_are_refused():
    clicks = rename(make_clicks(synthetic("dtl_high")), ("near", "far"))
    with pytest.raises(CameraBelowFloor, match="swapped"):
        solve(clicks, setup="dtl_high")


def test_a_camera_beyond_the_net_is_refused():
    """Swapping both left and right and near and far turns the court around the net."""
    clicks = rename(rename(make_clicks(synthetic("dtl_high")), ("left", "right")), ("near", "far"))
    with pytest.raises(CameraBeyondNet, match="turned around"):
        solve(clicks, setup="dtl_high")


STRONG_BARREL = {"k1": -0.4, "k2": 0.0}
"""This lens stops growing 609 px from the image centre at f = 1000, inside the 1101 px corners."""


def test_a_lens_that_folds_inside_the_clicks_is_refused(monkeypatch: pytest.MonkeyPatch):
    # The fit's barrier keeps the fold beyond the clicks, so this check is the last guard.
    # A negative margin turns the barrier off. Every click but one lies inside this lens's
    # fold, and a misplaced click near the image corner, which the robust loss ignores, lies
    # past it.
    monkeypatch.setattr(solver, "FOLD_MARGIN", -1.0)
    clicks = make_clicks(looking_at(**SETUPS["dtl_high"], **STRONG_BARREL))
    clicks.keypoints["near_left_corner"] = (5.0, HEIGHT - 5.0)
    with pytest.raises(FoldingLens, match="folds"):
        solve(clicks, setup="dtl_high")


def test_a_misplaced_far_click_has_the_worst_held_back_error():
    """With the barrier on, the same misplaced click is fitted around and shows as the worst."""
    clicks = make_clicks(looking_at(**SETUPS["dtl_high"], **STRONG_BARREL))
    clicks.keypoints["near_left_corner"] = (5.0, HEIGHT - 5.0)
    fit = solve(clicks, setup="dtl_high")
    worst = max(fit.held_back_px, key=lambda name: fit.held_back_px[name])
    assert worst == "near_left_corner"


FOLDS_IN_CORNERS = {"k1": -0.2, "k2": -0.01}
"""A lens that folds 830 px from the centre at f = 1000: beyond the court, inside the corners."""


def test_a_lens_that_folds_beyond_every_click_is_accepted():
    truth = looking_at(**SETUPS["dtl_high"], **FOLDS_IN_CORNERS)
    clicks = make_clicks(truth, noise_px=1.0)
    camera = solve(clicks, setup="dtl_high").camera

    assert fold_radius_px(camera) < np.hypot(WIDTH / 2, HEIGHT / 2)
    # The floor functions stop at the fold, so the image corners map nowhere.
    corners = np.array([[0.5, 0.5], [WIDTH - 0.5, HEIGHT - 0.5]])
    assert np.isnan(image_to_court(camera, corners, video_size=VIDEO)).all()
    # Every vertex of the visible region maps back inside the image.
    region = np.array(camera.visible_region)
    back = court_to_image(camera, region, video_size=VIDEO)
    assert np.isfinite(back).all()
    assert (back >= -1e-6).all() and (back[:, 0] <= WIDTH + 1e-6).all()
    assert (back[:, 1] <= HEIGHT + 1e-6).all()


def test_a_fit_that_does_not_converge_is_refused(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(solver, "MAX_EVALUATIONS", 2)
    with pytest.raises(FitDidNotConverge):
        solve(make_clicks(synthetic("diagonal"), noise_px=0.5), setup="diagonal")


def test_every_refusal_is_a_calibration_error():
    for error in (
        TooFewKeypoints,
        CollinearKeypoints,
        HeldBackErrorUndefined,
        CameraBelowFloor,
        CameraBeyondNet,
        FoldingLens,
        FitDidNotConverge,
    ):
        assert issubclass(error, solver.CalibrationError)


# Reliability over noise. People click to a pixel or two, so 20 noisy sets of clicks per
# setup must all fit.

SWEEP_SEEDS = range(20)
SWEEP_NOISE_PX = 1.0
MINIMUM_LINES = ("far_baseline", "left_sideline", "right_sideline")


def refusals(setup: str, **limits: Any) -> list[str]:
    truth = synthetic(setup)
    failed = []
    for seed in SWEEP_SEEDS:
        clicks = make_clicks(truth, noise_px=SWEEP_NOISE_PX, seed=seed, **limits)
        try:
            solve(clicks, setup=truth.setup)
        except solver.CalibrationError as error:
            failed.append(f"seed {seed}: {type(error).__name__}: {error}")
    return failed


@pytest.mark.parametrize("setup", ["dtl_low", "dtl_high", "diagonal"])
def test_full_clicks_with_1_px_noise_always_fit(setup: str):
    assert refusals(setup) == []


@pytest.mark.parametrize("setup", ["dtl_low", "dtl_high", "diagonal"])
def test_the_minimum_clicks_with_1_px_noise_always_fit(setup: str):
    assert refusals(setup, keypoints=FOUR, lines=MINIMUM_LINES) == []


FIVE_WITH_A_BASELINE = (
    "far_left_corner",
    "far_baseline_centre",
    "far_right_corner",
    "far_kitchen_left",
    "far_kitchen_right",
)


@pytest.mark.parametrize("setup", ["dtl_low", "dtl_high", "diagonal"])
def test_five_keypoints_with_3_on_a_baseline_have_a_stable_held_back_error(setup: str):
    """Leaving out a kitchen keypoint leaves 3 on the baseline and 1 off it."""
    truth = synthetic(setup)
    errors = []
    for seed in SWEEP_SEEDS:
        clicks = make_clicks(
            truth,
            noise_px=SWEEP_NOISE_PX,
            seed=seed,
            keypoints=FIVE_WITH_A_BASELINE,
            lines=MINIMUM_LINES,
        )
        fit = solve(clicks, setup=truth.setup)
        errors.append(max(fit.held_back_px.values()))
    assert max(errors) < 6 * SWEEP_NOISE_PX


def test_a_bad_start_fails_fast_so_the_second_start_runs(monkeypatch: pytest.MonkeyPatch):
    """On this seed the homography start's plain pass never converges. It must give up fast.

    A normal solve, with both starts and every leave-one-out refit, takes about 800 residual
    evaluations. Counting them, not seconds, keeps the test steady on slow CI runners.
    """
    calls = [0]
    residuals = solver._Problem.residuals

    def counted(problem: Any, params: np.ndarray) -> np.ndarray:
        calls[0] += 1
        return residuals(problem, params)

    monkeypatch.setattr(solver._Problem, "residuals", counted)
    truth = synthetic("dtl_low")
    fit = solve(make_clicks(truth, noise_px=1.0, seed=113), setup="dtl_low")

    assert calls[0] < 3000
    assert np.linalg.norm(centre_of(fit.camera) - centre_of(truth)) < 0.5


# The contract examples


def test_the_example_clicks_give_the_example_camera():
    """Pins the solver, the two contract examples and the floor functions together."""
    root = Path(__file__).parents[2] / "contracts"
    clicks = CameraClicks.model_validate_json((root / "camera_clicks.example.json").read_text())
    want = CameraCalibration.model_validate_json((root / "camera.example.json").read_text())

    got = solve(clicks, setup="dtl_low").camera

    assert got.intrinsics.fx == pytest.approx(want.intrinsics.fx, rel=0.01)
    assert got.distortion.k1 == pytest.approx(want.distortion.k1, abs=0.02)
    assert got.distortion.k2 == pytest.approx(want.distortion.k2, abs=0.02)
    assert np.linalg.norm(centre_of(got) - centre_of(want)) < 0.2
    assert angle_between_deg(got, want) < 0.2
    assert got.reprojection_error_px < 2.0


# Warnings


@pytest.mark.parametrize("setup", ["dtl_low", "dtl_high"])
def test_a_down_the_line_camera_without_net_tops_gets_a_warning(setup: str):
    truth = synthetic(setup)
    without = solve(make_clicks(truth, net_tops=()), setup=truth.setup)
    with_tops = solve(make_clicks(truth), setup=truth.setup)
    assert any("net tops" in w for w in without.warnings)
    assert with_tops.warnings == []


def test_a_diagonal_camera_without_net_tops_gets_no_warning():
    truth = synthetic("diagonal")
    assert solve(make_clicks(truth, net_tops=()), setup="diagonal").warnings == []


# The visibility mask


def _inside(polygon: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Even-odd point-in-polygon test."""
    x, y = points[:, 0:1], points[:, 1:2]
    x0, y0 = polygon[:, 0], polygon[:, 1]
    x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
    crosses = (y0 > y) != (y1 > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        at = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
    return ((crosses & (x < at)).sum(axis=1) % 2) == 1


@pytest.mark.parametrize("setup", ["dtl_low", "dtl_high", "diagonal", "folds_in_corners"])
def test_the_visible_region_is_the_true_floor_footprint(setup: str):
    if setup == "folds_in_corners":
        truth = looking_at(**SETUPS["dtl_high"], **FOLDS_IN_CORNERS)
    else:
        truth = synthetic(setup)
    camera = solve(make_clicks(truth), setup=truth.setup).camera
    region = np.array(camera.visible_region)

    assert region[:, 0].min() >= -10 - 1e-9 and region[:, 0].max() <= 30 + 1e-9
    assert region[:, 1].min() >= -10 - 1e-9 and region[:, 1].max() <= 54 + 1e-9

    xs, ys = np.meshgrid(np.arange(-9.75, 30, 0.5), np.arange(-9.75, 54, 0.5))
    floor = np.column_stack([xs.ravel(), ys.ravel()])
    pixels = court_to_image(truth, floor, video_size=VIDEO)
    margin = 0.01 * HEIGHT
    finite = np.isfinite(pixels).all(axis=1)
    px, py = np.where(finite, pixels[:, 0], -1e9), np.where(finite, pixels[:, 1], -1e9)
    seen = (px > margin) & (px < WIDTH - margin) & (py > margin) & (py < HEIGHT - margin)
    unseen = (
        ~finite | (px < -margin) | (px > WIDTH + margin) | (py < -margin) | (py > HEIGHT + margin)
    )
    # Past the lens fold the truth gives NaN. The fitted fold sits a little off the true one,
    # so points within 2% of the fold's radius count as neither seen nor unseen.
    cam = np.column_stack([floor, np.zeros(len(floor))]) @ rotation(truth.rotation).T
    cam += np.asarray(truth.translation)
    radius = np.hypot(cam[:, 0], cam[:, 1]) / cam[:, 2]
    near_fold = np.abs(radius / max_radius(truth) - 1) < 0.02
    seen &= ~near_fold
    unseen &= ~near_fold
    inside = _inside(region, floor)
    assert seen.sum() > 100
    assert inside[seen].all()
    assert not inside[unseen].any()


# Imports


def test_importing_the_solver_does_not_import_scipy():
    script = (
        "import sys\n"
        "import dinkdata.court.solver\n"
        "assert 'scipy' not in sys.modules, 'scipy was imported'\n"
        "print('ok')\n"
    )
    root = Path(__file__).parents[2]
    out = subprocess.run(
        [sys.executable, "-c", script], cwd=root, capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
