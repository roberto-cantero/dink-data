"""`dink ingest`: ids, split rules, privacy and the upload to R2 (issue #39)."""

import pyarrow.parquet as pq
import pytest

from dinkdata.contracts import ids
from dinkdata.contracts.catalog import CATALOG, CatalogRow
from dinkdata.contracts.frames import FRAMES
from dinkdata.data import ingest
from dinkdata.video import ffmpeg
from tests.fixtures.ffmpeg_clips import RATE, SECONDS, make_game_clip, needs_ffmpeg
from tests.fixtures.folder_store import FolderStore

KEY = b"k" * 16
GAME = ingest.Game(session_id="SESSIONSECRET123", facility="Secret Courts", court="court3")


def video_id() -> str:
    return ids.video_id(GAME.session_id, KEY)


@pytest.fixture
def store(tmp_path):
    return FolderStore(tmp_path / "r2")


def catalog_row(**changes) -> CatalogRow:
    row = {
        "video_id": video_id(),
        "facility_id": ids.facility_id(GAME.facility, KEY),
        "camera_id": ingest.make_ids(GAME, KEY).camera_id,
        "uploaded_at": None,
        "duration_s": 2.0,
        "fps_nominal": 30.0,
        "size_bytes": 1000,
        "setup": None,
        "split": "train",
        "fetched": True,
        "notes": None,
    }
    return CatalogRow.model_validate(row | changes)


def save_catalog(store: FolderStore, tmp_path, rows: list[CatalogRow]) -> None:
    path = tmp_path / "catalog.parquet"
    CATALOG.write(CATALOG.table(rows), path)
    store.put(path, ingest.CATALOG_PATH)
    store.puts.clear()


@pytest.mark.parametrize("raw", ["3", "court3", " Court3 ", "COURT 3"])
def test_court_accepts_a_number_or_the_dashboard_name(raw):
    assert ingest.parse_court(raw) == "court3"


@pytest.mark.parametrize("raw", ["", "court", "0", "court03", "three"])
def test_court_rejects_anything_else(raw):
    with pytest.raises(ValueError):
        ingest.parse_court(raw)


def test_ids_use_the_same_hmac_as_dink_id():
    made = ingest.make_ids(GAME, KEY)
    assert made.video_id == ids.video_id(GAME.session_id, KEY)
    assert made.facility_id == ids.facility_id(GAME.facility, KEY)
    assert made.camera_id == ids.camera_id("Secret Courts/court3", KEY)


def test_the_same_court_at_two_facilities_is_two_cameras():
    other = ingest.Game(session_id="S2", facility="Other Courts", court="court3")
    assert ingest.make_ids(GAME, KEY).camera_id != ingest.make_ids(other, KEY).camera_id


def test_a_new_facility_needs_a_split():
    empty = CATALOG.table([])
    with pytest.raises(ValueError, match="--split"):
        ingest.choose_split(empty, "f_0000000000000000", None)
    assert ingest.choose_split(empty, "f_0000000000000000", "test") == "test"


def test_a_known_facility_keeps_its_split():
    catalog = CATALOG.table([catalog_row(split="dev")])
    facility = ids.facility_id(GAME.facility, KEY)
    assert ingest.choose_split(catalog, facility, None) == "dev"
    assert ingest.choose_split(catalog, facility, "dev") == "dev"
    with pytest.raises(ValueError, match="dev"):
        ingest.choose_split(catalog, facility, "train")


def test_redact_removes_every_secret():
    text = "/Users/me/court3_SESSIONSECRET123.mp4 from Secret Courts"
    out = ingest.redact(text, ["SESSIONSECRET123", "Secret Courts", ""])
    assert "SESSIONSECRET123" not in out
    assert "Secret Courts" not in out
    assert "[hidden]" in out


def test_a_file_named_after_the_session_is_refused(tmp_path, store):
    source = tmp_path / "court3_sessionsecret123.mp4"
    source.write_bytes(b"not a video")
    with pytest.raises(ValueError, match="Rename"):
        ingest.ingest(source, GAME, KEY, store, tmp_path / "videos")
    assert store.puts == []


def test_a_game_already_in_r2_is_skipped_without_any_work(tmp_path, store, monkeypatch):
    save_catalog(store, tmp_path, [catalog_row()])
    for name in (f"{video_id()}.mp4", f"{video_id()}.frames.parquet"):
        (tmp_path / name).write_bytes(b"x")
        store.put(tmp_path / name, f"videos/{name}")
    store.puts.clear()
    monkeypatch.setattr(ffmpeg, "remux_video_only", _fail)
    source = tmp_path / "game.mp4"
    source.write_bytes(b"x")
    report = ingest.ingest(source, GAME, KEY, store, tmp_path / "videos")
    assert report.already_ingested
    assert report.split == "train"
    assert store.puts == []


def test_a_catalogued_game_with_another_camera_is_an_error(tmp_path, store):
    save_catalog(store, tmp_path, [catalog_row(camera_id="c_0000000000000000")])
    source = tmp_path / "game.mp4"
    source.write_bytes(b"x")
    with pytest.raises(ValueError, match="court"):
        ingest.ingest(source, GAME, KEY, store, tmp_path / "videos")


def _fail(*_args, **_kwargs):
    raise AssertionError("should not run")


@needs_ffmpeg
def test_ingest_uploads_the_video_frames_and_catalog_rows(tmp_path, store):
    source = make_game_clip(tmp_path / "game.mp4")
    report = ingest.ingest(source, GAME, KEY, store, tmp_path / "videos", split="train")

    vid = video_id()
    assert report.video_id == vid
    assert report.new_facility
    assert report.frames == SECONDS * RATE - 1
    assert report.dropped == 1
    assert report.duplicates == 0
    assert store.puts == [
        f"videos/{vid}.mp4",
        f"videos/{vid}.frames.parquet",
        ingest.ID_MAP_PATH,
        ingest.CATALOG_PATH,
    ]
    assert (tmp_path / "videos" / f"{vid}.mp4").is_file()

    frames = FRAMES.read(store.root / f"videos/{vid}.frames.parquet")
    assert len(frames) == report.frames
    [row] = CATALOG.rows(CATALOG.read(store.root / ingest.CATALOG_PATH))
    assert row.video_id == vid
    assert row.camera_id == report.camera_id
    assert row.split == "train"
    assert row.fetched
    assert row.uploaded_at is None
    assert row.setup is None
    assert row.fps_nominal == pytest.approx(RATE)
    assert row.size_bytes == (tmp_path / "videos" / f"{vid}.mp4").stat().st_size

    [private] = pq.read_table(store.root / ingest.ID_MAP_PATH).to_pylist()
    assert private == {
        "video_id": vid,
        "session_id": GAME.session_id,
        "facility_id": report.facility_id,
        "facility": GAME.facility,
        "camera_id": report.camera_id,
        "court": GAME.court,
    }


@needs_ffmpeg
def test_running_twice_uploads_nothing_the_second_time(tmp_path, store):
    source = make_game_clip(tmp_path / "game.mp4")
    ingest.ingest(source, GAME, KEY, store, tmp_path / "videos", split="train")
    store.puts.clear()
    report = ingest.ingest(source, GAME, KEY, store, tmp_path / "videos")
    assert report.already_ingested
    assert store.puts == []


@needs_ffmpeg
def test_a_second_game_at_the_facility_reuses_its_split(tmp_path, store):
    source = make_game_clip(tmp_path / "game.mp4")
    ingest.ingest(source, GAME, KEY, store, tmp_path / "videos", split="dev")
    second = ingest.Game(session_id="SESSION2", facility=GAME.facility, court="court1")
    report = ingest.ingest(source, second, KEY, store, tmp_path / "videos")
    assert report.split == "dev"
    assert not report.new_facility
    catalog = CATALOG.read(store.root / ingest.CATALOG_PATH)
    assert catalog.column("split").to_pylist() == ["dev", "dev"]
    assert len(pq.read_table(store.root / ingest.ID_MAP_PATH)) == 2


@needs_ffmpeg
def test_only_missing_files_are_uploaded(tmp_path, store):
    source = make_game_clip(tmp_path / "game.mp4")
    ingest.ingest(source, GAME, KEY, store, tmp_path / "videos", split="train")
    (store.root / f"videos/{video_id()}.frames.parquet").unlink()
    store.puts.clear()
    report = ingest.ingest(source, GAME, KEY, store, tmp_path / "videos")
    assert not report.already_ingested
    assert store.puts == [f"videos/{video_id()}.frames.parquet"]
