"""`dink ingest`: prepare one hand-downloaded game (DESIGN 6.1, docs/DATA.md, issue #39).

Ingest drops the audio, saves every frame's timestamp, gives the game its HMAC ids (ADR 0016),
uploads the video and its frames to R2 and adds a row to the catalog and to the private id map.
Files already in R2 are skipped, so a failed run can simply be run again.

Two people can ingest at the same time (K3, issue #79). Each catalog file is updated with a
conditional write: ingest reads the file and its ETag, adds its row to what it read, and writes
only if no one changed the file since. Otherwise it reads again and retries. The split check
runs again on every retry, so two first ingests from a new facility can't give it two splits.

The session id, facility and court come from a hidden prompt as a `Game`. They go only into
`catalog/id_map.parquet`, which stays in R2, and never into output, logs or errors.
"""

import re
import tempfile
from collections.abc import Callable, Iterable
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
ATTEMPTS = 5
"""Conditional writes to try before giving up, when other ingests keep changing a file."""

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


def _read_catalog(local: Path | None) -> pa.Table:
    return CATALOG.read(local) if local is not None else CATALOG.table([])


def _read_id_map(local: Path | None) -> pa.Table:
    if local is None:
        return ID_MAP_SCHEMA.empty_table()
    table = pq.read_table(local)
    if not table.schema.equals(ID_MAP_SCHEMA, check_metadata=True):
        raise ValueError(f"{ID_MAP_PATH} doesn't match {ID_MAP_SCHEMA.metadata}")
    return table


def _add_row(
    store: Store,
    path: str,
    local: Path,
    read: Callable[[Path | None], pa.Table],
    add: Callable[[pa.Table], pa.Table | None],
    write: Callable[[pa.Table, Path], None],
) -> bool:
    """Update a shared table in R2 with a conditional write, and retry if another ingest wrote
    it first. `add` gets the latest table and returns it with the new row, or None when the row
    is already there. Returns whether it wrote."""
    for _ in range(ATTEMPTS):
        etag = store.get_versioned(path, local)
        table = add(read(local if etag is not None else None))
        if table is None:
            return False
        write(table, local)
        if store.put_if(local, path, etag):
            return True
    raise ValueError(f"{path} kept changing during {ATTEMPTS} tries. Run ingest again.")


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
        def add_id_map_row(id_map: pa.Table) -> pa.Table | None:
            if made.video_id in id_map.column("video_id").to_pylist():
                return None
            return pa.concat_tables([id_map, _id_map_row(game, made)])

        if _add_row(
            store, ID_MAP_PATH, work / "id_map.parquet", _read_id_map, add_id_map_row,
            lambda table, path: pq.write_table(table, path),
        ):  # fmt: skip
            uploaded.append(ID_MAP_PATH)

        def add_catalog_row(latest: pa.Table) -> pa.Table | None:
            if made.video_id in latest.column("video_id").to_pylist():
                return None
            new_row = CatalogRow(
                video_id=made.video_id,
                facility_id=made.facility_id,
                camera_id=made.camera_id,
                uploaded_at=None,
                duration_s=info.duration_s,
                fps_nominal=ffmpeg.nominal_fps(info.pts, info.time_base),
                size_bytes=local.stat().st_size,
                setup=None,
                # Another ingest may have given a new facility its split since the first read.
                split=choose_split(latest, made.facility_id, chosen),
                fetched=True,
                notes=None,
            )
            return pa.concat_tables([latest, CATALOG.table([new_row])])

        if _add_row(
            store, CATALOG_PATH, work / "catalog.parquet", _read_catalog, add_catalog_row,
            CATALOG.write,
        ):  # fmt: skip
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
