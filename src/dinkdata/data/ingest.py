"""`dink ingest`: prepare one hand-downloaded game (DESIGN 6.1, docs/DATA.md, issue #39).

Ingest drops the audio, saves every frame's timestamp, gives the game its HMAC ids (ADR 0016),
uploads the video and its frames to R2 and adds a row to the catalog and to the private id map.
Files already in R2 are skipped, so a failed run can simply be run again.

The session id, facility and court come from a hidden prompt as a `Game`. They go only into
`catalog/id_map.parquet`, which stays in R2, and never into output, logs or errors.
"""

import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from dinkdata.contracts import ids
from dinkdata.contracts.catalog import CATALOG, CatalogRow
from dinkdata.contracts.common import Split
from dinkdata.contracts.frames import FRAMES
from dinkdata.contracts.tables import column
from dinkdata.data import r2
from dinkdata.data.r2 import Store
from dinkdata.video import ffmpeg

CATALOG_PATH = "catalog/catalog.parquet"
ID_MAP_PATH = "catalog/id_map.parquet"

# Private, so it has no contract in contracts/ (see contracts/catalog.py).
ID_MAP_SCHEMA = pa.schema(
    [
        pa.field("video_id", pa.string(), nullable=False),
        pa.field("session_id", pa.string(), nullable=False),
        pa.field("facility_id", pa.string(), nullable=False),
        pa.field("facility", pa.string(), nullable=False),
        pa.field("camera_id", pa.string(), nullable=False),
        pa.field("court", pa.string(), nullable=False),
    ],
    metadata={"schema": "dinkdata.id_map/v1"},
)

_COURT = re.compile(r"(?:court)?\s*([1-9][0-9]*)")


@dataclass(frozen=True)
class Game:
    """What the hidden prompt gives for one game. Private: never print it."""

    session_id: str
    facility: str
    court: str
    """As the dashboard names it, such as `court3`. See `parse_court`."""

    def secrets(self) -> list[str]:
        return [self.session_id, self.facility]


@dataclass(frozen=True)
class Ids:
    video_id: str
    facility_id: str
    camera_id: str


@dataclass(frozen=True)
class Report:
    """What one ingest did. Holds opaque ids and counts only, so it is safe to print."""

    video_id: str
    facility_id: str
    camera_id: str
    split: Split
    new_facility: bool
    already_ingested: bool
    uploaded: list[str]
    frames: int | None = None
    dropped: int | None = None
    duplicates: int | None = None


def parse_court(raw: str) -> str:
    """`3`, `court3` or `Court 3` as `court3`, the dashboard's name for the court."""
    match = _COURT.fullmatch(raw.strip().lower())
    if match is None:
        raise ValueError("the court must be a number such as 3, or a name such as court3")
    return f"court{match.group(1)}"


def make_ids(game: Game, key: bytes) -> Ids:
    """The game's ids. A camera is one court at one facility, so its id hashes both."""
    facility = game.facility.strip()
    return Ids(
        video_id=ids.video_id(game.session_id, key),
        facility_id=ids.facility_id(facility, key),
        camera_id=ids.camera_id(f"{facility}/{game.court}", key),
    )


def choose_split(catalog: pa.Table, facility_id: str, requested: Split | None) -> Split:
    """A known facility keeps its split. A new facility needs one, because a test facility
    must never land in train by accident."""
    known = {
        split
        for facility, split in zip(
            catalog.column("facility_id").to_pylist(),
            catalog.column("split").to_pylist(),
            strict=True,
        )
        if facility == facility_id
    }
    if not known:
        if requested is None:
            raise ValueError("This facility is new. Choose its split with --split train|dev|test.")
        return requested
    [split] = known
    if requested is not None and requested != split:
        raise ValueError(f"This facility's games are in the {split} split, not {requested}.")
    return split


def redact(text: str, secrets: Iterable[str]) -> str:
    """`text` with every non-empty secret replaced by `[hidden]`, ignoring case."""
    for secret in sorted((s for s in secrets if s.strip()), key=len, reverse=True):
        text = re.sub(re.escape(secret.strip()), "[hidden]", text, flags=re.IGNORECASE)
    return text


def missing_tools() -> list[str]:
    return ffmpeg.missing_tools() + (["rclone"] if r2.rclone_missing() else [])


def _load(store: Store, path: str, local: Path) -> pa.Table | None:
    if not store.exists(path):
        return None
    store.get(path, local)
    return pq.read_table(local)


def _load_catalog(store: Store, local: Path) -> pa.Table:
    if _load(store, CATALOG_PATH, local) is None:
        return CATALOG.table([])
    return CATALOG.read(local)


def _load_id_map(store: Store, local: Path) -> pa.Table:
    table = _load(store, ID_MAP_PATH, local)
    if table is None:
        return ID_MAP_SCHEMA.empty_table()
    if not table.schema.equals(ID_MAP_SCHEMA, check_metadata=True):
        raise ValueError(f"{ID_MAP_PATH} doesn't match {ID_MAP_SCHEMA.metadata}")
    return table


def ingest(
    source: Path,
    game: Game,
    key: bytes,
    store: Store,
    videos: Path,
    split: Split | None = None,
) -> Report:
    """Prepare one downloaded MP4 and upload it. `videos` keeps a local copy for the studio."""
    made = make_ids(game, key)
    if game.session_id.strip().lower() in str(source).lower():
        raise ValueError(
            "The file name holds the session id. Rename the file, such as to game.mp4, "
            "and run ingest again."
        )
    video_key = f"videos/{made.video_id}.mp4"
    frames_key = f"videos/{made.video_id}.frames.parquet"
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        catalog = _load_catalog(store, work / "catalog.parquet")
        id_map = _load_id_map(store, work / "id_map.parquet")

        rows = {r.video_id: r for r in CATALOG.rows(catalog)}
        row = rows.get(made.video_id)
        if row is not None and row.camera_id != made.camera_id:
            raise ValueError(
                "This game is in the catalog with another camera. Check the facility and court."
            )
        new_facility = made.facility_id not in {r.facility_id for r in rows.values()}
        chosen = row.split if row is not None else choose_split(catalog, made.facility_id, split)
        have_video, have_frames = store.exists(video_key), store.exists(frames_key)
        report = Report(
            video_id=made.video_id,
            facility_id=made.facility_id,
            camera_id=made.camera_id,
            split=chosen,
            new_facility=new_facility,
            already_ingested=row is not None and have_video and have_frames,
            uploaded=[],
        )
        if report.already_ingested:
            return report

        local = videos / f"{made.video_id}.mp4"
        if have_video:
            # Time the copy in R2, so the frames always match the video others download.
            videos.mkdir(parents=True, exist_ok=True)
            store.get(video_key, local)
        else:
            ffmpeg.remux_video_only(source, local)
        info = ffmpeg.probe(local)
        frames = ffmpeg.build_frames(info.pts, info.time_base, ffmpeg.frame_hashes(local))
        FRAMES.write(frames, work / "frames.parquet")

        uploaded = []
        if not have_video:
            store.put(local, video_key)
            uploaded.append(video_key)
        if not have_frames:
            store.put(work / "frames.parquet", frames_key)
            uploaded.append(frames_key)

        # The catalog goes last, so it never lists a game whose files aren't in R2 yet.
        if made.video_id not in id_map.column("video_id").to_pylist():
            id_map = pa.concat_tables([id_map, _id_map_row(game, made)])
            pq.write_table(id_map, work / "id_map.parquet")
            store.put(work / "id_map.parquet", ID_MAP_PATH, overwrite=True)
            uploaded.append(ID_MAP_PATH)
        if row is None:
            new_row = CatalogRow(
                video_id=made.video_id,
                facility_id=made.facility_id,
                camera_id=made.camera_id,
                uploaded_at=None,
                duration_s=info.duration_s,
                fps_nominal=ffmpeg.nominal_fps(info.pts, info.time_base),
                size_bytes=local.stat().st_size,
                setup=None,
                split=chosen,
                fetched=True,
                notes=None,
            )
            catalog = pa.concat_tables([catalog, CATALOG.table([new_row])])
            CATALOG.write(catalog, work / "catalog.parquet")
            store.put(work / "catalog.parquet", CATALOG_PATH, overwrite=True)
            uploaded.append(CATALOG_PATH)

    return replace(
        report,
        uploaded=uploaded,
        frames=len(frames),
        dropped=int(column(frames, "dropped_before").sum()),
        duplicates=int(column(frames, "duplicate").sum()),
    )


def _id_map_row(game: Game, made: Ids) -> pa.Table:
    return pa.Table.from_pylist(
        [
            {
                "video_id": made.video_id,
                "session_id": game.session_id.strip(),
                "facility_id": made.facility_id,
                "facility": game.facility.strip(),
                "camera_id": made.camera_id,
                "court": game.court,
            }
        ],
        schema=ID_MAP_SCHEMA,
    )
