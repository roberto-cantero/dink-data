"""The studio's local server. The page plays the video and sends marks; Python does the rest.

Start it with `dink studio --rallies <video_id> --labeller <handle>`. It listens on
127.0.0.1 only. Labels and crops go to a local folder (`dinkdata.studio.store`), and the
video's file name never reaches the page or a label file.
"""

import base64
import binascii
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from dinkdata.contracts.common import VIDEO_ID_PATTERN, PlayerId, Seconds, load, to_json
from dinkdata.contracts.rallies import RallyLabels
from dinkdata.studio import rally, store

STATIC = Path(__file__).parent / "static"
MAX_CROP_BYTES = 2_000_000
_PNG = b"\x89PNG\r\n\x1a\n"
_PLAYERS: tuple[PlayerId, ...] = ("p1", "p2", "p3", "p4")


class Crop(BaseModel):
    player: PlayerId
    t: Seconds
    png_base64: str = Field(description="The cropped PNG, base64 encoded.")


def create_app(video: Path, video_id: str, labeller: str, labels: Path) -> FastAPI:
    """The rally-mode app for one video and one labeller."""
    if not re.fullmatch(VIDEO_ID_PATTERN, video_id):
        raise ValueError(f"not a video id: {video_id!r}. Make one with `dink id video`.")
    labeller_pattern = RallyLabels.model_json_schema()["properties"]["labeller"]["pattern"]
    if not re.fullmatch(labeller_pattern, labeller):
        raise ValueError(f"the labeller must be a short lowercase handle, not {labeller!r}")
    if not video.is_file():
        raise ValueError(f"no video at {video}. Save it there, named by its id.")
    folder = store.rally_folder(labels, video_id, labeller)

    app = FastAPI(title="DinkData studio", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "rally.html")

    @app.get("/video")
    def get_video() -> FileResponse:
        # No filename, so the response carries no Content-Disposition with the file's name.
        return FileResponse(video, media_type="video/mp4")

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
            errors = [str(e["msg"]).removeprefix("Value error, ") for e in error.errors()]
            return JSONResponse({"errors": errors}, status_code=422)
        path = store.write_new_version(folder, to_json(labels_model).encode(), ".json")
        red = sum(v.red for v in rally.review(marks).rallies)
        return JSONResponse(
            {"version": int(path.stem[1:]), "path": str(path.relative_to(labels)), "red": red}
        )

    @app.post("/api/crops")
    def save_crop(crop: Crop) -> dict[str, int]:
        try:
            data = base64.b64decode(crop.png_base64, validate=True)
        except binascii.Error:
            raise HTTPException(422, "the crop isn't base64") from None
        if not data.startswith(_PNG) or len(data) > MAX_CROP_BYTES:
            raise HTTPException(422, "the crop must be a PNG under 2 MB")
        path = store.write_new_version(_crops(crop.player), data, ".png")
        return {"version": int(path.stem[1:])}

    @app.get("/api/crops/{player}")
    def get_crop(player: PlayerId) -> FileResponse:
        path = store.latest(_crops(player), ".png")
        if path is None:
            raise HTTPException(404, f"no crop for {player} yet")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})

    def _crops(player: PlayerId) -> Path:
        return store.crop_folder(labels, video_id, labeller, player)

    return app
