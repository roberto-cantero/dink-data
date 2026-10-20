"""The studio server, with the synthetic clip (no real footage)."""

import base64
import json

import pytest
from fastapi.testclient import TestClient

from dinkdata.contracts.common import load
from dinkdata.contracts.rallies import RallyLabels
from dinkdata.studio.server import create_app

VIDEO_ID = "v_5eed00000000a001"
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16).decode()

MARKS = {
    "games": [{"start_t": 0.1, "end_t": 1.9, "finished": False, "target": 11}],
    "rallies": [
        {"t": 0.2, "end_t": 0.6, "server": "p1", "side": "right"},
        {"t": 0.8, "end_t": 1.2, "server": "p1", "side": "left"},
    ],
}


@pytest.fixture
def labels(tmp_path):
    return tmp_path / "labels"


@pytest.fixture
def client(synthetic_clip, labels):
    return TestClient(create_app(synthetic_clip, VIDEO_ID, "marti", labels))


def test_the_page_and_its_files_load(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "rally.js" in page.text
    assert client.get("/static/rally.js").status_code == 200


def test_the_video_streams_in_ranges_without_its_file_name(client, synthetic_clip):
    response = client.get("/video", headers={"Range": "bytes=0-99"})
    assert response.status_code == 206
    assert len(response.content) == 100
    assert synthetic_clip.name not in json.dumps(dict(response.headers))


def test_a_new_session_starts_empty(client):
    session = client.get("/api/session").json()
    assert session["video_id"] == VIDEO_ID
    assert session["version"] == 0
    assert session["marks"] == {"games": [], "rallies": []}
    assert session["crops"] == []


def test_check_replays_the_score(client):
    review = client.post("/api/check", json=MARKS).json()
    assert [r["score_before"] for r in review["rallies"]] == ["0-0-2", "1-0-2"]
    assert review["rallies"][0]["winner_team"] == "A"


def test_saves_are_validated_versioned_and_reloaded(client, labels):
    first = client.post("/api/save", json=MARKS).json()
    second = client.post("/api/save", json=MARKS).json()
    assert (first["version"], second["version"]) == (1, 2)
    assert first["path"] == f"gold-rallies/{VIDEO_ID}/marti/v1.json"
    saved = load(RallyLabels, labels / first["path"])
    assert saved.games[0].rallies[1].score_before == "1-0-2"
    session = client.get("/api/session").json()
    assert session["version"] == 2
    assert len(session["marks"]["rallies"]) == 2


def test_an_incomplete_save_writes_nothing(client, labels):
    marks = {"games": [{"start_t": 0.1}], "rallies": [{"t": 0.2}]}
    response = client.post("/api/save", json=marks)
    assert response.status_code == 422
    assert len(response.json()["errors"]) == 3
    assert not labels.exists()


def test_a_save_the_contract_rejects_writes_nothing(client, labels):
    marks = json.loads(json.dumps(MARKS))
    marks["games"][0]["finished"] = True
    response = client.post("/api/save", json=marks)
    assert response.status_code == 422
    assert "game_end_mismatch" in " ".join(response.json()["errors"])
    assert not labels.exists()


def test_crops_are_stored_beside_the_labels(client, labels):
    assert client.get("/api/crops/p1").status_code == 404
    response = client.post("/api/crops", json={"player": "p1", "t": 0.5, "png_base64": PNG})
    assert response.json() == {"version": 1}
    assert (labels / f"gold-rallies/{VIDEO_ID}/marti/crops/p1/v1.png").is_file()
    assert client.get("/api/crops/p1").content.startswith(b"\x89PNG")
    assert client.get("/api/session").json()["crops"] == ["p1"]


@pytest.mark.parametrize(
    "body",
    [
        {"player": "p1", "t": 0.5, "png_base64": "not base64!"},
        {"player": "p1", "t": 0.5, "png_base64": base64.b64encode(b"GIF89a").decode()},
        {"player": "p5", "t": 0.5, "png_base64": PNG},
    ],
)
def test_bad_crops_are_rejected(client, body):
    assert client.post("/api/crops", json=body).status_code == 422


@pytest.mark.parametrize(
    ("video_id", "labeller", "message"),
    [("1234", "marti", "video id"), (VIDEO_ID, "Marti L", "handle")],
)
def test_the_app_refuses_raw_ids_and_names(synthetic_clip, labels, video_id, labeller, message):
    with pytest.raises(ValueError, match=message):
        create_app(synthetic_clip, video_id, labeller, labels)
