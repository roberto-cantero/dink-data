"""Calibrate mode over HTTP, with the synthetic clip, a synthetic camera and the folder store.

No real footage. The clip is a top-down court with a ball that moves, so the median picture
has no ball and a single frame does. The clicks come from a synthetic down-the-line camera
scaled to the clip's 320x180, so they fit as a real camera's would.
"""

import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from dinkdata.contracts.camera_clicks import FLOOR_KEYPOINTS, NET_TOPS, CameraClicks
from dinkdata.contracts.catalog import CatalogRow
from dinkdata.contracts.common import load
from dinkdata.contracts.frames import FRAMES, FrameRow
from dinkdata.court.floor import court_lines_image, court_to_image, load_camera
from dinkdata.court.keypoints import KEYPOINTS
from dinkdata.court.solver import line_centre
from dinkdata.studio import calibrate
from dinkdata.studio.server import create_calibrate_app
from dinkdata.video.reader import VideoReader
from tests.court.cameras import BARREL, SETUPS, camera_json, looking_at
from tests.fixtures.folder_store import FolderStore
from tests.fixtures.make_clip import court_to_px

CAMERA = "c_5eed00000000ca01"
OTHER_CAMERA = "c_5eed00000000ca02"
VIDEO_ID = "v_5eed00000000ca11"
WIDTH, HEIGHT = 320, 180
SCALE = WIDTH / 1920
KEYPOINT_NAMES = [
    "near_left_corner",
    "near_right_corner",
    "near_kitchen_left",
    "near_kitchen_right",
    "far_kitchen_left",
    "far_kitchen_right",
    "near_kitchen_centre",
    "far_kitchen_centre",
]


def synthetic_camera():
    """The dtl_high synthetic camera, scaled from 1920x1080 to the clip's 320x180."""
    s = SETUPS["dtl_high"]
    full = looking_at(s["x"], s["y"], s["height"], s["target"], setup="dtl_high", **BARREL)
    record = camera_json(
        full.rotation, full.translation, 1000.0 * SCALE, BARREL["k1"], BARREL["k2"]
    )
    record["image_size"] = {"width": WIDTH, "height": HEIGHT}
    record["intrinsics"] = {"fx": 1000.0 * SCALE, "fy": 1000.0 * SCALE, "cx": 160, "cy": 90}
    from dinkdata.contracts.camera import CameraCalibration

    return CameraCalibration.model_validate(record)


def clicks_body(names=KEYPOINT_NAMES, setup: str | None = "dtl_high", seed=0, noise_px=0.1) -> dict:
    """What the page sends: the camera's projection of each named keypoint's line centre."""
    camera = synthetic_camera()
    rng = np.random.default_rng(seed)

    def project(name):
        x, y, h = KEYPOINTS[name]
        pixel = court_to_image(
            camera, np.array([[*line_centre((x, y)), h]]), video_size=(WIDTH, HEIGHT)
        )
        return [float(v) for v in pixel[0] + rng.normal(0, noise_px, 2)]

    body = {"keypoints": {n: project(n) for n in names}, "setup": setup}
    body["net_tops"] = {n: project(n) for n in ("net_top_left", "net_top_centre", "net_top_right")}
    return body


@pytest.fixture
def frames(synthetic_clip, tmp_path):
    with VideoReader(synthetic_clip) as reader:
        times = [float(t) for t in reader.times]
    rows = [FrameRow(frame=i, t=t, dropped_before=0, duplicate=False) for i, t in enumerate(times)]
    path = tmp_path / f"{VIDEO_ID}.frames.parquet"
    FRAMES.write(FRAMES.table(rows), path)
    return path


@pytest.fixture
def cameras(tmp_path):
    return tmp_path / "cameras"


@pytest.fixture
def r2(tmp_path):
    return FolderStore(tmp_path / "r2")


def make_app(synthetic_clip, frames, cameras, store, camera_id=CAMERA):
    return create_calibrate_app(
        synthetic_clip, frames, camera_id, VIDEO_ID, "robby", cameras, store=store
    )


@pytest.fixture
def client(synthetic_clip, frames, cameras, r2):
    return TestClient(make_app(synthetic_clip, frames, cameras, r2))


def picture(response) -> np.ndarray:
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return np.asarray(image)[:, :, ::-1]  # BGR to RGB


def is_ball(rgb: np.ndarray) -> bool:
    """The clip's ball is yellow (255, 230, 0) on a green court (60, 120, 60)."""
    r, g, b = (int(v) for v in rgb)
    return r > 160 and g > 150 and b < 120


def test_the_page_and_its_files_load(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "calibrate.js" in page.text
    assert client.get("/static/calibrate.js").status_code == 200
    assert client.get("/static/calibrate.css").status_code == 200


def test_the_session_names_the_camera_video_and_sampled_frames(client):
    session = client.get("/api/session").json()
    assert session["camera_id"] == CAMERA
    assert session["video_id"] == VIDEO_ID
    assert (session["width"], session["height"]) == (WIDTH, HEIGHT)
    assert session["frames"] == calibrate.sample_frames(60)
    assert len(session["frames"]) == calibrate.SAMPLES
    assert session["frames"][0] == 0 and session["frames"][-1] == 59
    assert session["median_url"] == f"/api/picture/{CAMERA}/{VIDEO_ID}/median"
    assert session["frame_url"] == f"/api/picture/{CAMERA}/{VIDEO_ID}/frame"
    assert session["versions"] == []
    assert session["r2"] == {"on": True}
    points = [p["name"] for p in session["diagram"]["points"]]
    assert points[:12] == list(FLOOR_KEYPOINTS)
    assert points[12:] == list(NET_TOPS)
    assert session["diagram"]["setups"] == ["dtl_low", "dtl_high", "diagonal"]


def test_the_median_picture_has_no_ball_and_a_single_frame_does(client):
    session = client.get("/api/session").json()
    median = picture(client.get(session["median_url"]))
    assert median.shape == (HEIGHT, WIDTH, 3)
    for index in (0, 30, 59):
        single = picture(client.get(f"{session['frame_url']}/{index}"))
        t = index / 59  # the clip's own drawing parameter, not a time
        x, y = court_to_px(10 + 4 * t, 40 - 25 * t)
        assert is_ball(single[y, x])
        assert not is_ball(median[y, x])


def test_a_frame_outside_the_video_is_404(client):
    assert client.get(f"/api/picture/{CAMERA}/{VIDEO_ID}/frame/60").status_code == 404


def test_two_cameras_never_get_each_others_picture(synthetic_clip, frames, cameras, r2):
    first = TestClient(make_app(synthetic_clip, frames, cameras, r2, CAMERA))
    second = TestClient(make_app(synthetic_clip, frames, cameras, r2, OTHER_CAMERA))
    a, b = first.get("/api/session").json(), second.get("/api/session").json()
    assert a["median_url"] != b["median_url"]
    assert a["frame_url"] != b["frame_url"]
    assert first.get(b["median_url"]).status_code == 404
    assert second.get(a["median_url"]).status_code == 404
    assert first.get(f"{b['frame_url']}/0").status_code == 404
    other_video = f"/api/picture/{CAMERA}/v_5eed00000000ca12/median"
    assert first.get(other_video).status_code == 404


def test_a_fit_returns_errors_the_worst_keypoints_and_the_fitted_court(client):
    response = client.post("/api/fit", json=clicks_body())
    assert response.status_code == 200, response.text
    fit = response.json()
    assert set(fit["held_back_px"]) == set(KEYPOINT_NAMES)
    assert fit["error_px"] == pytest.approx(np.mean(list(fit["held_back_px"].values())))
    assert fit["error_px"] < 1.0
    errors = fit["held_back_px"]
    assert fit["worst"] == sorted(errors, key=errors.get, reverse=True)[:3]
    assert set(fit["lines"]) == {
        "far_baseline",
        "near_baseline",
        "left_sideline",
        "right_sideline",
        "far_kitchen_line",
        "near_kitchen_line",
        "far_centre_line",
        "near_centre_line",
    }
    assert all(len(points) == calibrate.LINE_SAMPLES for points in fit["lines"].values())
    near = [p for p in fit["lines"]["near_kitchen_line"] if p is not None]
    assert len(near) == calibrate.LINE_SAMPLES
    assert len([p for p in fit["net"] if p is not None]) > 2
    assert fit["fitted"]["near_left_corner"] == pytest.approx(
        clicks_body()["keypoints"]["near_left_corner"], abs=1.0
    )
    assert fit["warnings"] == []


def test_the_overlay_draws_line_centres_not_boundaries(client):
    fit = client.post("/api/fit", json=clicks_body(noise_px=0.0)).json()
    camera = synthetic_camera()
    drawn = np.array(fit["lines"]["near_baseline"], dtype=float)
    # The near baseline's centre is 1 in inside the court, at y = 44 - 1/12 ft, from the left
    # sideline's centre to the right one's.
    x = np.linspace(1 / 12, 20 - 1 / 12, calibrate.LINE_SAMPLES)
    floor = np.column_stack([x, np.full_like(x, 44 - 1 / 12)])
    centre = court_to_image(camera, floor, video_size=(WIDTH, HEIGHT))
    boundary = court_lines_image(camera, video_size=(WIDTH, HEIGHT))["near_baseline"]
    to_centre = np.linalg.norm(drawn - centre, axis=1)
    to_boundary = np.linalg.norm(drawn - boundary, axis=1)
    assert np.max(to_centre) < 0.05
    assert np.min(to_boundary) > 0.3


def test_a_fit_with_too_few_keypoints_is_refused_with_the_solvers_message(client):
    body = clicks_body(names=KEYPOINT_NAMES[:3])
    response = client.post("/api/fit", json=body)
    assert response.status_code == 422
    assert "at least 4 floor keypoints" in response.json()["errors"][0]


def test_a_fit_needs_a_setup(client):
    response = client.post("/api/fit", json=clicks_body(setup=None))
    assert response.status_code == 422
    assert "setup" in response.json()["errors"][0]


def test_a_click_outside_the_picture_is_refused(client):
    body = clicks_body()
    body["keypoints"]["near_left_corner"] = [WIDTH + 5.0, 10.0]
    response = client.post("/api/fit", json=body)
    assert response.status_code == 422
    assert "outside" in response.json()["errors"][0]


def test_a_dtl_camera_with_no_net_tops_gets_a_warning(client):
    body = clicks_body()
    body["net_tops"] = {}
    fit = client.post("/api/fit", json=body).json()
    assert "net tops" in fit["warnings"][0]


def test_saves_write_valid_versions_locally_and_in_r2_and_never_overwrite(client, cameras, r2):
    first = client.post("/api/save", json={**clicks_body(), "single_frame": 30})
    assert first.status_code == 200, first.text
    assert first.json() == {"version": 1, "path": f"{CAMERA}/v1", "uploaded": True}
    v1 = {
        name: (cameras / CAMERA / "v1" / name).read_bytes()
        for name in ("camera.json", "clicks.json")
    }

    second = client.post("/api/save", json=clicks_body(setup="dtl_low", seed=1)).json()
    assert second["version"] == 2
    for name, data in v1.items():
        assert (cameras / CAMERA / "v1" / name).read_bytes() == data
        assert (r2.root / "cameras" / CAMERA / "v1" / name).read_bytes() == data

    camera = load_camera(CAMERA, root=cameras)
    assert (camera.version, camera.setup, camera.source) == (2, "dtl_low", "clicks")
    assert camera.reprojection_error_px > 0
    clicks = load(CameraClicks, cameras / CAMERA / "v2" / "clicks.json")
    assert (clicks.version, clicks.video_id, clicks.labeller) == (2, VIDEO_ID, "robby")
    assert clicks.frames == calibrate.sample_frames(60)
    first_clicks = load(CameraClicks, cameras / CAMERA / "v1" / "clicks.json")
    assert first_clicks.single_frame == 30
    assert set(first_clicks.keypoints) == set(KEYPOINT_NAMES)
    assert len(first_clicks.net_tops) == 3
    assert load_camera(CAMERA, 1, root=cameras).setup == "dtl_high"
    assert sorted(r2.puts) == sorted(
        f"cameras/{CAMERA}/v{n}/{name}" for n in (1, 2) for name in ("camera.json", "clicks.json")
    )
    assert client.get("/api/session").json()["versions"] == [1, 2]


def test_a_save_numbers_after_versions_already_in_r2(client, cameras, r2):
    stray = r2.root / "cameras" / CAMERA / "v4" / "camera.json"
    stray.parent.mkdir(parents=True)
    stray.write_text("{}")
    assert client.post("/api/save", json=clicks_body()).json()["version"] == 5
    assert stray.read_text() == "{}"
    assert load_camera(CAMERA, root=cameras).version == 5


def test_a_save_takes_the_next_number_when_another_save_takes_it_first(client, cameras, r2):
    others = json.dumps({"someone": "else"})

    def another_mac_saves_v1(path: str) -> None:
        if path == f"cameras/{CAMERA}/v1/clicks.json":
            target = r2.root / path
            target.parent.mkdir(parents=True)
            target.write_text(others)
            r2.before_write = None

    r2.before_write = another_mac_saves_v1
    saved = client.post("/api/save", json=clicks_body()).json()
    assert saved["version"] == 2
    assert (r2.root / "cameras" / CAMERA / "v1" / "clicks.json").read_text() == others
    assert not (cameras / CAMERA / "v1").exists()
    assert load_camera(CAMERA, root=cameras).version == 2
    assert load(CameraClicks, cameras / CAMERA / "v2" / "clicks.json").version == 2


def test_a_refused_save_writes_nothing(client, cameras, r2):
    response = client.post("/api/save", json=clicks_body(names=KEYPOINT_NAMES[:3]))
    assert response.status_code == 422
    assert not cameras.exists()
    assert r2.puts == []


def test_a_save_that_r2_fails_writes_nothing_locally(client, cameras, r2):
    from dinkdata.data.r2 import RcloneError

    def offline(folder):
        raise RcloneError("no network")

    r2.files = offline
    response = client.post("/api/save", json=clicks_body())
    assert response.status_code == 502
    assert "R2" in response.json()["errors"][0]
    assert not cameras.exists()


def test_with_r2_off_saves_number_after_the_local_versions(synthetic_clip, frames, cameras):
    client = TestClient(make_app(synthetic_clip, frames, cameras, None))
    assert client.get("/api/session").json()["r2"] == {"on": False}
    first = client.post("/api/save", json=clicks_body()).json()
    second = client.post("/api/save", json=clicks_body()).json()
    assert (first, second) == (
        {"version": 1, "path": f"{CAMERA}/v1", "uploaded": False},
        {"version": 2, "path": f"{CAMERA}/v2", "uploaded": False},
    )
    assert load_camera(CAMERA, root=cameras).version == 2


def test_a_bad_camera_id_or_labeller_stops_the_app(synthetic_clip, frames, cameras):
    with pytest.raises(ValueError, match="camera id"):
        create_calibrate_app(synthetic_clip, frames, "court3", VIDEO_ID, "robby", cameras)
    with pytest.raises(ValueError, match="handle"):
        create_calibrate_app(synthetic_clip, frames, CAMERA, VIDEO_ID, "Robby C", cameras)


def catalog_row(video_id: str, camera_id: str) -> CatalogRow:
    return CatalogRow(
        video_id=video_id,
        facility_id="f_5eed00000000ca21",
        camera_id=camera_id,
        uploaded_at=None,
        duration_s=60.0,
        fps_nominal=30.0,
        size_bytes=1000,
        setup=None,
        split="train",
        fetched=True,
        notes=None,
    )


def test_the_camera_s_first_catalog_video_is_picked_unless_another_is_asked_for():
    rows = [
        catalog_row("v_5eed00000000ca31", OTHER_CAMERA),
        catalog_row("v_5eed00000000ca32", CAMERA),
        catalog_row("v_5eed00000000ca33", CAMERA),
    ]
    assert calibrate.pick_video(rows, CAMERA) == "v_5eed00000000ca32"
    assert calibrate.pick_video(rows, CAMERA, "v_5eed00000000ca33") == "v_5eed00000000ca33"
    with pytest.raises(ValueError, match="isn't a video of camera"):
        calibrate.pick_video(rows, CAMERA, "v_5eed00000000ca31")
    with pytest.raises(ValueError, match="no video of camera"):
        calibrate.pick_video(rows, "c_5eed00000000ca03")


@pytest.mark.parametrize(
    ("count", "expected"), [(1, [0]), (3, [0, 1, 2]), (49, list(range(0, 49, 2)))]
)
def test_sampled_frames_spread_from_first_to_last(count, expected):
    assert calibrate.sample_frames(count) == expected
