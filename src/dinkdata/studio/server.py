"""The studio's local server. The page shows the video and sends marks; Python does the rest.

Start it with `dink studio --rallies <video_id>` for rally mode or `dink studio --label
<video_id>` for events mode, each with `--labeller <handle>`. It listens on 127.0.0.1 only,
and the video's file name never reaches the page or a label file.

Rally mode plays the video in the browser, which needs no exact frames. Events mode serves
each frame exactly, by index, from the video reader, and every `t` it saves comes from the
frame's timestamp (`dinkdata.studio.frames`). Saves are validated against the contracts,
written locally as a new version (`dinkdata.studio.store`), then uploaded to R2
(`dinkdata.studio.sync`).
"""

import base64
import binascii
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, TypeVar

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from dinkdata.contracts.common import VIDEO_ID_PATTERN, Frame, PlayerId, Seconds, load, to_json
from dinkdata.contracts.frames import FRAMES
from dinkdata.contracts.game_log import EventLog
from dinkdata.contracts.rallies import RallyLabels
from dinkdata.contracts.tables import column
from dinkdata.data.r2 import RcloneError
from dinkdata.studio import events, rally, store, sync

STATIC = Path(__file__).parent / "static"
MAX_CROP_BYTES = 2_000_000
_PNG = b"\x89PNG\r\n\x1a\n"
_PLAYERS: tuple[PlayerId, ...] = ("p1", "p2", "p3", "p4")
_HANDLE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

Mode = Literal["rally", "events"]
T = TypeVar("T")


class Crop(BaseModel):
    player: PlayerId
    t: Seconds
    png_base64: str = Field(description="The cropped PNG, base64 encoded.")


class BoundaryRequest(BaseModel):
    """R: the playhead as a frame when paused, or as the browser's time while playing."""

    marks: events.Marks
    frame: Frame | None = None
    t: Seconds | None = None


class R2:
    """The upload state of one label folder. With no store, labels stay local."""

    def __init__(self, labels_store: sync.LabelStore | None, labels: Path, folder: str) -> None:
        self.store = labels_store
        self.labels = labels
        self.folder = folder
        self.error: str | None = None

    def pull(self) -> None:
        self._run(sync.pull)

    def push(self) -> bool:
        """Upload what R2 lacks. True if everything is in R2 afterwards."""
        return self._run(sync.push) is not None

    def status(self) -> dict[str, Any]:
        if self.store is None:
            return {"on": False, "pending": None, "error": None}
        return {"on": True, "pending": self._run(sync.pending), "error": self.error}

    def _run(self, action: Callable[[sync.LabelStore, Path, str], T]) -> T | None:
        if self.store is None:
            return None
        try:
            result = action(self.store, self.labels, self.folder)
        except (RcloneError, OSError) as error:
            self.error = str(error)
            return None
        self.error = None
        return result


def create_app(
    video: Path,
    video_id: str,
    labeller: str,
    labels: Path,
    *,
    mode: Mode = "rally",
    frames: Path | None = None,
    store: sync.LabelStore | None = None,
    rallies_from: str | None = None,
) -> FastAPI:
    """The studio app for one video, one labeller and one mode.

    `frames` is the video's frames.parquet, which events mode needs. `store` is R2, or None
    to keep labels local. `rallies_from` is whose rally gold events mode builds on, by
    default the labeller's own.
    """
    if not re.fullmatch(VIDEO_ID_PATTERN, video_id):
        raise ValueError(f"not a video id: {video_id!r}. Make one with `dink id video`.")
    for handle in (labeller, rallies_from):
        if handle is not None and not _HANDLE.fullmatch(handle):
            raise ValueError(f"a labeller must be a short lowercase handle, not {handle!r}")
    if not video.is_file():
        raise ValueError(f"no video at {video}. Save it there, named by its id.")
    if mode == "rally":
        return _rally_app(video, video_id, labeller, labels, store)
    return _events_app(video, video_id, labeller, labels, frames, store, rallies_from)


def _base_app(page: str, lifespan: Callable[[FastAPI], Any] | None = None) -> FastAPI:
    app = FastAPI(title="DinkData studio", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / page)

    return app


def _video_route(app: FastAPI, video: Path) -> None:
    @app.get("/video")
    def get_video() -> FileResponse:
        # No filename, so the response carries no Content-Disposition with the file's name.
        return FileResponse(video, media_type="video/mp4")


def _errors(error: ValidationError) -> list[str]:
    return [str(e["msg"]).removeprefix("Value error, ") for e in error.errors()]


# ---- rally mode ----


def _rally_app(
    video: Path, video_id: str, labeller: str, labels: Path, labels_store: sync.LabelStore | None
) -> FastAPI:
    folder = store.rally_folder(labels, video_id, labeller)
    r2 = R2(labels_store, labels, str(folder.relative_to(labels)))
    app = _base_app("rally.html")
    _video_route(app, video)

    @app.get("/api/session")
    def session() -> dict[str, Any]:
        path = store.latest(folder, ".json")
        marks = rally.from_labels(load(RallyLabels, path)) if path else rally.Marks()
        return {
            "video_id": video_id,
            "labeller": labeller,
            "version": len(store.versions(folder, ".json")),
            "marks": marks.model_dump(mode="json"),
            "crops": [p for p in _PLAYERS if store.latest(_crops(p), ".png")],
        }

    @app.post("/api/check")
    def check(marks: rally.Marks) -> rally.Review:
        return rally.review(marks)

    @app.post("/api/save")
    def save(marks: rally.Marks) -> JSONResponse:
        try:
            labels_model = rally.to_labels(marks, video_id, labeller)
        except rally.IncompleteMarks as error:
            return JSONResponse({"errors": error.problems}, status_code=422)
        except ValidationError as error:
            return JSONResponse({"errors": _errors(error)}, status_code=422)
        r2.pull()
        path = store.write_new_version(folder, to_json(labels_model).encode(), ".json")
        red = sum(v.red for v in rally.review(marks).rallies)
        return JSONResponse(
            {
                "version": int(path.stem[1:]),
                "path": str(path.relative_to(labels)),
                "red": red,
                "uploaded": r2.push(),
                "r2_on": r2.store is not None,
                "r2_error": r2.error,
            }
        )

    @app.post("/api/crops")
    def save_crop(crop: Crop) -> dict[str, Any]:
        try:
            data = base64.b64decode(crop.png_base64, validate=True)
        except binascii.Error:
            raise HTTPException(422, "the crop isn't base64") from None
        if not data.startswith(_PNG) or len(data) > MAX_CROP_BYTES:
            raise HTTPException(422, "the crop must be a PNG under 2 MB")
        path = store.write_new_version(_crops(crop.player), data, ".png")
        return {"version": int(path.stem[1:]), "uploaded": r2.push()}

    @app.get("/api/crops/{player}")
    def get_crop(player: PlayerId) -> FileResponse:
        path = store.latest(_crops(player), ".png")
        if path is None:
            raise HTTPException(404, f"no crop for {player} yet")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})

    def _crops(player: PlayerId) -> Path:
        return store.crop_folder(labels, video_id, labeller, player)

    return app


# ---- events mode ----


def _events_app(
    video: Path,
    video_id: str,
    labeller: str,
    labels: Path,
    frames: Path | None,
    labels_store: sync.LabelStore | None,
    rallies_from: str | None,
) -> FastAPI:
    from dinkdata.studio.frames import FrameSource  # needs the cv extra, which rally mode doesn't

    if frames is None or not frames.is_file():
        raise ValueError(f"events mode needs the video's frames.parquet, not {frames}")
    source_handle = rallies_from or labeller
    gold_folder = store.rally_folder(labels, video_id, source_handle)
    events_folder = labels / store.GOLD_EVENTS / video_id / labeller
    gold_r2 = R2(labels_store, labels, str(gold_folder.relative_to(labels)))
    r2 = R2(labels_store, labels, str(events_folder.relative_to(labels)))
    gold_r2.pull()
    r2.pull()
    gold = _load_gold(gold_folder, labels_store, labels, video_id, source_handle)

    table = FRAMES.read(frames)
    source = FrameSource(video, table)
    footage = events.Footage(
        video_id=video_id,
        times=source.times,
        fps_nominal=source.fps_nominal,
        dropped_frames=int(column(table, "dropped_before").sum()),
        width=source.width,
        height=source.height,
    )
    basis = events.Basis(gold, footage)
    crops = {}
    for p in _PLAYERS:
        crop = store.latest(store.crop_folder(labels, video_id, source_handle, p), ".png")
        crops[p] = str(Path("labels") / crop.relative_to(labels)) if crop else None
    r2.push()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        source.close()

    app = _base_app("events.html", lifespan)
    _video_route(app, video)

    @app.get("/api/session")
    def session() -> dict[str, Any]:
        path = store.latest(events_folder, ".json")
        marks = events.merge(basis, load(EventLog, path) if path else None)
        return {
            "video_id": video_id,
            "labeller": labeller,
            "rallies_from": source_handle,
            "version": len(store.versions(events_folder, ".json")),
            "frames": len(source),
            "width": source.width,
            "height": source.height,
            "r2": r2.status(),
            "marks": marks.model_dump(mode="json"),
            "review": events.review(marks, basis).model_dump(mode="json"),
        }

    @app.get("/api/frames")
    def frame_times() -> dict[str, list[float]]:
        return {"t": source.times}

    @app.get("/api/frame/{index}")
    def frame(index: int) -> Response:
        if not 0 <= index < len(source):
            raise HTTPException(404, f"frame {index} is outside the video's {len(source)} frames")
        # A frame's picture never changes, so the browser may keep it.
        headers = {"Cache-Control": "private, max-age=86400, immutable"}
        return Response(source.jpeg(index), media_type="image/jpeg", headers=headers)

    @app.get("/api/snap")
    def snap(t: Seconds) -> dict[str, Any]:
        index = footage.nearest(t)
        return {"frame": index, "t": source.times[index]}

    @app.post("/api/check")
    def check(marks: events.Marks) -> events.Review:
        return events.review(marks, basis)

    @app.post("/api/boundary")
    def boundary(request: BoundaryRequest) -> dict[str, Any]:
        if request.frame is not None:
            at = min(request.frame, basis.last)
        elif request.t is not None:
            at = footage.nearest(request.t)
        else:
            raise HTTPException(422, "send the playhead's frame or t")
        try:
            index, field = events.boundary_near(request.marks, basis, at)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        return {"rally": index, "field": field, "frame": at}

    @app.post("/api/save")
    def save(marks: events.Marks) -> JSONResponse:
        try:
            log = events.to_log(marks, basis, crops)
        except events.IncompleteMarks as error:
            return JSONResponse({"errors": error.problems}, status_code=422)
        except ValidationError as error:
            return JSONResponse({"errors": _errors(error)}, status_code=422)
        r2.pull()
        path = store.write_new_version(events_folder, to_json(log).encode(), ".json")
        rallies = [r for g in log.games for r in g.rallies]
        return JSONResponse(
            {
                "version": int(path.stem[1:]),
                "path": str(path.relative_to(labels)),
                "reviewed": sum(r.reviewed for r in rallies),
                "rallies": len(rallies),
                "uploaded": r2.push(),
                "r2_on": r2.store is not None,
                "r2_error": r2.error,
            }
        )

    return app


def _load_gold(
    folder: Path,
    labels_store: sync.LabelStore | None,
    labels: Path,
    video_id: str,
    handle: str,
) -> RallyLabels:
    path = store.latest(folder, ".json")
    if path is None:
        try:
            found = sync.handles(labels_store, labels, store.GOLD_RALLIES, video_id)
        except RcloneError:
            found = sync.handles(None, labels, store.GOLD_RALLIES, video_id)
        others = (
            f" Rally gold exists from {', '.join(found)}: pass --rallies-from." if found else ""
        )
        raise ValueError(
            f"events mode builds on rally gold, and {handle} has none for {video_id}. Label "
            f"its rallies first with `dink studio --rallies {video_id}`.{others}"
        )
    try:
        return load(RallyLabels, path)
    except ValidationError as error:
        raise ValueError(
            f"{path.relative_to(labels)} isn't valid rally gold ({_errors(error)[0]}). If it is "
            "v1, run `dink contracts upgrade-rallies`."
        ) from None
