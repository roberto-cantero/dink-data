"""The studio server in events mode, on the gappy clip (no real footage).

The clip paints each camera frame's number into its picture and drops frames 10 and 30 to
32, so these tests can tell which frame came back and whether its time is the right one.
"""

import random

import cv2
import numpy as np
import pyarrow as pa
import pytest
from fastapi.testclient import TestClient

from dinkdata.contracts.common import load, to_json
from dinkdata.contracts.frames import FRAMES, FrameRow, check_log_frames
from dinkdata.contracts.game_log import EventLog
from dinkdata.data.r2 import RcloneError
from dinkdata.studio import rally, sync
from dinkdata.studio.server import create_app
from tests.fixtures.folder_store import FolderStore
from tests.fixtures.make_gappy_clip import KEPT, camera_t, read_number

VIDEO_ID = "v_5eed00000000e051"
GOLD = f"gold-rallies/{VIDEO_ID}/marti"
EVENTS = f"gold-events/{VIDEO_ID}/marti"


def frames_table(times: list[float], dropped: int = 0) -> pa.Table:
    rows = [
        FrameRow(frame=i, t=t, dropped_before=dropped if i == 1 else 0, duplicate=False)
        for i, t in enumerate(times)
    ]
    return FRAMES.table(rows)


def gold_labels(handle: str = "marti") -> str:
    marks = rally.Marks.model_validate(
        {
            "games": [{"start_t": 0.1, "end_t": 1.9, "finished": False, "target": 11}],
            "rallies": [
                {"t": 0.2, "end_t": 0.6, "server": "p1", "side": "right", "winner": "A"},
                {"t": 0.8, "end_t": 1.5, "server": "p1", "side": "left", "winner": "B"},
            ],
        }
    )
    return to_json(rally.to_labels(marks, VIDEO_ID, handle))


@pytest.fixture
def times() -> list[float]:
    return [camera_t(n) for n in KEPT]


@pytest.fixture
def frames(tmp_path, times):
    path = tmp_path / "videos" / f"{VIDEO_ID}.frames.parquet"
    path.parent.mkdir(parents=True)
    FRAMES.write(frames_table(times, dropped=4), path)
    return path


@pytest.fixture
def labels(tmp_path):
    folder = tmp_path / "labels" / GOLD
    folder.mkdir(parents=True)
    (folder / "v1.json").write_text(gold_labels())
    return tmp_path / "labels"


@pytest.fixture
def r2(tmp_path):
    return FolderStore(tmp_path / "r2")


@pytest.fixture
def client(gappy_clip, frames, labels, r2):
    app = create_app(gappy_clip, VIDEO_ID, "marti", labels, mode="events", frames=frames, store=r2)
    return TestClient(app)


def picture(response) -> np.ndarray:
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return np.asarray(image)


def settled(session: dict) -> dict:
    marks = session["marks"]
    for r in marks["rallies"]:
        r["confirmed"] = ["start", "end", "winner"]
        r["end_reason"] = "unexplained"
    return marks


# ---- frames are exact by timestamp ----


def test_frame_times_are_the_videos_with_its_gaps(client, times):
    served = client.get("/api/frames").json()["t"]
    assert served == times
    assert served == pytest.approx([camera_t(n) for n in KEPT])


def test_every_frame_comes_back_exactly_in_any_order(client):
    order = list(range(len(KEPT)))
    random.Random(51).shuffle(order)
    for index in order:
        assert read_number(picture(client.get(f"/api/frame/{index}"))) == KEPT[index]


@pytest.mark.parametrize("start", [0, 9, 10, 11, 12, 28, 29, 40])
def test_stepping_forward_back_and_by_ten_lands_on_the_right_frames(client, start):
    """Around the dropped frame 10, the three dropped at 30 to 32 and the keyframes."""
    path = [start, start + 1, start + 11, start + 10, start + 9, start - 1]
    for index in [i for i in path if 0 <= i < len(KEPT)]:
        assert read_number(picture(client.get(f"/api/frame/{index}"))) == KEPT[index]


@pytest.mark.parametrize(
    ("t", "camera_frame"),
    [
        (0.0, 0),
        (camera_t(5) + 0.01, 5),
        (camera_t(5) + 0.02, 6),
        (camera_t(10) - 0.001, 9),  # frame 10 was dropped
        (camera_t(31) - 0.001, 29),  # inside the three-frame gap, nearer 29
        (camera_t(31) + 0.02, 33),  # inside the gap, nearer 33
        (99.0, 59),
    ],
)
def test_a_browser_time_snaps_to_the_nearest_frame(client, times, t, camera_frame):
    snapped = client.get("/api/snap", params={"t": t}).json()
    assert snapped == {"frame": KEPT.index(camera_frame), "t": times[KEPT.index(camera_frame)]}


def test_out_of_range_frames_are_404(client):
    assert client.get(f"/api/frame/{len(KEPT)}").status_code == 404
    assert client.get("/api/frame/-1").status_code in (404, 422)


def test_a_frames_table_that_disagrees_with_the_video_stops_the_app(
    gappy_clip, frames, labels, times
):
    FRAMES.write(frames_table([t + 0.01 if i else t for i, t in enumerate(times)]), frames)
    with pytest.raises(ValueError, match="frames.parquet"):
        create_app(gappy_clip, VIDEO_ID, "marti", labels, mode="events", frames=frames)


def test_the_page_cant_send_a_time(client):
    marks = settled(client.get("/api/session").json())
    start = marks["rallies"][0]["start_frame"]
    marks["rallies"][0]["events"] = [
        {"id": "a", "type": "hit", "frame": start + 1, "player": "p1", "t": 0.25}
    ]
    assert client.post("/api/save", json=marks).status_code == 422


# ---- the session, R and checks ----


def test_the_session_starts_from_rally_gold(client, times):
    session = client.get("/api/session").json()
    assert session["video_id"] == VIDEO_ID
    assert session["rallies_from"] == "marti"
    assert session["version"] == 0
    assert (session["width"], session["height"]) == (64, 48)
    assert session["r2"] == {"on": True, "pending": 0, "error": None}
    first = session["marks"]["rallies"][0]
    assert first["id"] == "g1_r1"
    assert times[first["start_frame"]] == pytest.approx(0.2, abs=0.02)
    assert session["review"]["rallies"][0]["server"] == "p1"


def test_r_picks_the_nearest_boundary_from_a_browser_time(client, times):
    marks = client.get("/api/session").json()["marks"]
    picked = client.post("/api/boundary", json={"marks": marks, "t": 0.63}).json()
    assert picked == {"rally": 0, "field": "end", "frame": KEPT.index(19)}


def test_check_proposes_and_derives(client):
    marks = client.get("/api/session").json()["marks"]
    start = marks["rallies"][1]["start_frame"]
    marks["rallies"][1]["events"] = [
        {"id": "a", "type": "hit", "frame": start + 1, "player": "p1"},
        {"id": "b", "type": "net", "frame": start + 4},
    ]
    view = client.post("/api/check", json=marks).json()["rallies"][1]
    assert view["proposed_end_reason"] == "net"
    assert view["events"][0] == {"id": "a", "shot_index": 1, "volley": False}


# ---- saves are validated, versioned, local first, then R2 ----


def test_saves_validate_and_version_with_times_from_frames(client, labels, frames, r2, times):
    marks = settled(client.get("/api/session").json())
    start = marks["rallies"][1]["start_frame"]
    marks["rallies"][1]["events"] = [
        {"id": "a", "type": "hit", "frame": start + 1, "player": "p1"},
        {"id": "b", "type": "bounce", "frame": start + 3, "image_xy": [30.5, 40.0]},
        {"id": "c", "type": "bounce", "frame": start + 6},
    ]
    first = client.post("/api/save", json=marks).json()
    second = client.post("/api/save", json=marks).json()
    assert (first["version"], second["version"]) == (1, 2)
    assert first["path"] == f"{EVENTS}/v1.json"
    assert first["uploaded"] is True and first["r2_on"] is True
    assert r2.puts == [f"labels/{EVENTS}/v1.json", f"labels/{EVENTS}/v2.json"]

    log = load(EventLog, labels / first["path"])
    assert log.schema_ == "dinkdata.events/v3" and log.camera is None
    assert check_log_frames(log, FRAMES.read(frames)) == []
    saved = log.games[0].rallies[1]
    assert [e.t for e in saved.events] == [times[e.frame] for e in saved.events]
    assert saved.reviewed

    session = client.get("/api/session").json()
    assert session["version"] == 2


def test_a_save_with_an_open_rally_writes_nothing(client, labels):
    marks = client.get("/api/session").json()["marks"]
    marks["rallies"][0]["end_frame"] = None
    response = client.post("/api/save", json=marks)
    assert response.status_code == 422
    assert any("Press R" in e for e in response.json()["errors"])
    assert not (labels / EVENTS).exists()


def test_a_failed_upload_keeps_the_local_save_and_the_next_save_uploads_both(client, r2):
    marks = client.get("/api/session").json()["marks"]
    put = r2.put

    def offline(local, path, overwrite=False):
        raise RcloneError("rclone failed: no network")

    r2.put = offline
    first = client.post("/api/save", json=marks).json()
    assert first["version"] == 1 and first["uploaded"] is False
    assert "no network" in first["r2_error"]
    assert client.get("/api/session").json()["r2"]["pending"] == 1

    r2.put = put
    second = client.post("/api/save", json=marks).json()
    assert second["uploaded"] is True
    assert r2.puts == [f"labels/{EVENTS}/v1.json", f"labels/{EVENTS}/v2.json"]


def test_a_save_numbers_after_versions_already_in_r2(gappy_clip, frames, labels, r2):
    """Another machine saved v1 and v2. This one saves v3, so nothing is overwritten."""
    (r2.root / "labels" / EVENTS).mkdir(parents=True)
    client = TestClient(
        create_app(gappy_clip, VIDEO_ID, "marti", labels, mode="events", frames=frames)
    )
    saved = client.post("/api/save", json=client.get("/api/session").json()["marks"]).json()
    for n in (1, 2):
        (r2.root / "labels" / EVENTS / f"v{n}.json").write_text(
            (labels / saved["path"]).read_text()
        )
    (labels / saved["path"]).unlink()

    client = TestClient(
        create_app(gappy_clip, VIDEO_ID, "marti", labels, mode="events", frames=frames, store=r2)
    )
    session = client.get("/api/session").json()
    assert session["version"] == 2
    assert client.post("/api/save", json=session["marks"]).json()["version"] == 3


def test_the_session_reopens_a_saved_file_merged_with_rally_gold(
    gappy_clip, frames, labels, client
):
    marks = settled(client.get("/api/session").json())
    start = marks["rallies"][0]["start_frame"]
    marks["rallies"][0]["events"] = [{"id": "a", "type": "hit", "frame": start + 1}]
    client.post("/api/save", json=marks)
    reopened = TestClient(
        create_app(gappy_clip, VIDEO_ID, "marti", labels, mode="events", frames=frames)
    )
    again = reopened.get("/api/session").json()
    assert again["version"] == 1
    assert again["marks"]["rallies"][0]["events"][0]["frame"] == start + 1
    assert again["review"]["uncertain"][0]["what"] == "hitter"


# ---- rally gold from R2, and whose ----


def test_rally_gold_and_crops_come_from_r2_when_missing_locally(gappy_clip, frames, tmp_path, r2):
    remote = r2.root / "labels" / GOLD
    (remote / "crops" / "p2").mkdir(parents=True)
    (remote / "v1.json").write_text(gold_labels())
    (remote / "crops" / "p2" / "v1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    labels = tmp_path / "fresh"
    app = create_app(gappy_clip, VIDEO_ID, "marti", labels, mode="events", frames=frames, store=r2)
    client = TestClient(app)
    assert (labels / GOLD / "v1.json").is_file()
    marks = client.get("/api/session").json()["marks"]
    log = load(EventLog, labels / client.post("/api/save", json=marks).json()["path"])
    assert [p.crop for p in log.players] == [None, f"labels/{GOLD}/crops/p2/v1.png", None, None]


def test_another_labellers_rally_gold_with_rallies_from(gappy_clip, frames, tmp_path):
    labels = tmp_path / "labels"
    folder = labels / f"gold-rallies/{VIDEO_ID}/robby"
    folder.mkdir(parents=True)
    (folder / "v1.json").write_text(gold_labels("robby"))
    with pytest.raises(ValueError, match="robby"):
        create_app(gappy_clip, VIDEO_ID, "marti", labels, mode="events", frames=frames)
    app = create_app(
        gappy_clip, VIDEO_ID, "marti", labels, mode="events", frames=frames, rallies_from="robby"
    )
    assert TestClient(app).get("/api/session").json()["rallies_from"] == "robby"


def test_events_mode_needs_a_frames_table(gappy_clip, labels):
    with pytest.raises(ValueError, match="frames"):
        create_app(gappy_clip, VIDEO_ID, "marti", labels, mode="events")


def test_the_events_page_and_its_files_load(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "events.js" in page.text
    assert client.get("/static/events.js").status_code == 200


# ---- the video and its frames from R2 ----


def test_the_video_and_its_frames_are_fetched_from_r2_when_missing(tmp_path, gappy_clip, frames):
    r2 = FolderStore(tmp_path / "remote")
    (r2.root / "videos").mkdir(parents=True)
    (r2.root / "videos" / f"{VIDEO_ID}.mp4").write_bytes(gappy_clip.read_bytes())
    (r2.root / "videos" / f"{VIDEO_ID}.frames.parquet").write_bytes(frames.read_bytes())
    videos = tmp_path / "local-videos"
    video, table = sync.fetch_video(r2, videos, VIDEO_ID)
    assert video.read_bytes() == gappy_clip.read_bytes()
    assert table.read_bytes() == frames.read_bytes()
    assert sorted(p.name for p in videos.iterdir()) == sorted([video.name, table.name])


def test_a_missing_video_without_r2_says_where_it_should_be(tmp_path):
    with pytest.raises(ValueError, match="data/videos"):
        sync.fetch_video(None, tmp_path / "data" / "videos", VIDEO_ID)


# ---- rally mode uploads too ----


def test_rally_mode_saves_go_to_r2(synthetic_clip, tmp_path, r2):
    labels = tmp_path / "labels"
    client = TestClient(create_app(synthetic_clip, VIDEO_ID, "marti", labels, store=r2))
    marks = {
        "games": [{"start_t": 0.1, "end_t": 1.9, "finished": False, "target": 11}],
        "rallies": [{"t": 0.2, "end_t": 0.6, "server": "p1", "side": "right", "winner": "A"}],
    }
    assert client.post("/api/save", json=marks).json()["uploaded"] is True
    assert r2.puts == [f"labels/{GOLD}/v1.json"]
