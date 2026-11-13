"""Ball clicks in CVAT: clip folders for CVAT tasks, and the converter to ball_labels (DESIGN 9).

CVAT numbers a task's frames 0, 1, 2 and so on, and decodes a video its own way. The
prototype's labels broke because those numbers didn't match the video (ADR 0001). So CVAT
never gets the MP4. `export_clip` decodes the frames with `VideoReader` and writes each one as
a JPEG named by its real frame index, zero-padded so that CVAT's name order is frame order. A
`manifest.json` beside them lists each task frame's real frame and `t`. The converter maps task
frame `i` to `manifest.frames[i]` and never computes a frame from a time.

The converter reads the "CVAT for video 1.1" export, the format that keeps each shape's
`keyframe` flag. A keyframe is a click, so `clicked` is true. Other shapes are frames CVAT
interpolated, so `clicked` is false. A frame marked outside, or with no ball shape, is hidden.
"""

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import Field, TypeAdapter, ValidationError, model_validator

from dinkdata.contracts.ball import BALL_LABELS, BallLabelRow
from dinkdata.contracts.common import (
    VIDEO_ID_PATTERN,
    Frame,
    Handle,
    Seconds,
    Split,
    StrictModel,
    VideoId,
)
from dinkdata.studio import store

LABEL = "ball"
BALL_LABELS_FOLDER = "ball"
CLIP_FRAMES = 60
"""About 2 seconds of a 30 fps video, the clip length in docs/LABELLING.md."""
JPEG_QUALITY = 95


def image_name(frame: int) -> str:
    return f"frame_{frame:07d}.jpg"


def clip_name(video_id: str, start: int) -> str:
    """The clip folder's name, which is also the CVAT task's name."""
    return f"{video_id}_f{start:06d}"


class ClipManifest(StrictModel):
    """`manifest.json` in a clip folder: the real frame and time of each CVAT task frame.

    A working file for the converter, not a pipeline contract.
    """

    name: str = Field(description="The clip folder's name. The CVAT task must have this name.")
    video_id: VideoId
    split: Split
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    frames: list[Frame] = Field(min_length=1, description="Task frame i is frames[i].")
    t: list[Seconds] = Field(min_length=1, description="The time of frames[i].")

    @model_validator(mode="after")
    def _rules(self) -> "ClipManifest":
        if len(self.frames) != len(self.t):
            raise ValueError("frames and t must have the same length")
        if any(b <= a for a, b in zip(self.frames, self.frames[1:], strict=False)):
            raise ValueError("frames must rise")
        return self


@dataclass(frozen=True)
class Clip:
    folder: Path
    manifest: ClipManifest


def export_clip(
    video: Path,
    video_id: str,
    split: Split,
    start: int,
    count: int,
    out: Path,
    frames: pa.Table | None = None,
) -> Clip:
    """Write frames `start` to `start + count - 1` as JPEGs plus a manifest, for one CVAT task.

    `frames` is the video's frames.parquet. When given, the reader checks it against the video.
    The folder must not exist yet, so a clip that is being labelled is never replaced.
    """
    import cv2

    from dinkdata.video.reader import VideoReader

    if not re.fullmatch(VIDEO_ID_PATTERN, video_id):
        raise ValueError(f"not a video id: {video_id!r}. Make one with `dink id video`.")
    folder = out / clip_name(video_id, start)
    if folder.exists():
        raise ValueError(f"{folder} already exists")
    with VideoReader(video, frames, fmt="bgr24") as reader:
        if count < 1 or start < 0 or start + count > len(reader):
            raise ValueError(
                f"frames {start} to {start + count - 1} are outside the video's {len(reader)}"
            )
        partial = folder.with_name(f"{folder.name}.partial")
        partial.mkdir(parents=True, exist_ok=False)
        indices, times = [], []
        width = height = 0
        for frame in reader.iter_frames(start, start + count):
            path = partial / image_name(frame.index)
            if not cv2.imwrite(str(path), frame.image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]):
                raise RuntimeError(f"couldn't write {path.name}")
            indices.append(frame.index)
            times.append(frame.t)
            height, width = frame.image.shape[:2]
    manifest = ClipManifest(
        name=folder.name,
        video_id=video_id,
        split=split,
        width=width,
        height=height,
        frames=indices,
        t=times,
    )
    (partial / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
    partial.rename(folder)
    return Clip(folder, manifest)


def load_clip(folder: Path) -> Clip:
    manifest = ClipManifest.model_validate(json.loads((folder / "manifest.json").read_text()))
    return Clip(folder, manifest)


@dataclass(frozen=True)
class Shape:
    """One ball shape of a CVAT track on one task frame."""

    frame: int
    x: float
    y: float
    outside: bool
    keyframe: bool


@dataclass(frozen=True)
class CvatTask:
    """What the converter needs from a "CVAT for video 1.1" export."""

    name: str
    size: int
    width: int | None
    height: int | None
    start_frame: int
    frame_filter: str
    tracks: list[list[Shape]]
    labels: set[str]


def _int(element: ElementTree.Element, path: str) -> int | None:
    text = element.findtext(path)
    return int(text) if text not in (None, "") else None


def _flag(shape: ElementTree.Element, name: str) -> bool:
    return shape.get(name, "0") == "1"


def parse_export(xml: str) -> CvatTask:
    """Parse the annotations.xml of a "CVAT for video 1.1" export."""
    root = ElementTree.fromstring(xml)
    task = root.find("meta/task")
    if task is None:
        raise ValueError('not a "CVAT for video 1.1" export: it has no meta/task')
    size = _int(task, "size")
    if size is None:
        raise ValueError("the export doesn't give the task's size")
    tracks, labels = [], set()
    for track in root.iter("track"):
        labels.add(track.get("label", ""))
        shapes = []
        for element in track:
            if element.tag != "points":
                raise ValueError(f"a {element.tag} shape in a track. Use a points label")
            coords = (element.get("points") or "").split(";")
            if len(coords) != 1:
                raise ValueError(f"frame {element.get('frame')}: a ball shape has one point")
            x, y = (float(v) for v in coords[0].split(","))
            shapes.append(
                Shape(
                    int(element.get("frame", "-1")),
                    x,
                    y,
                    _flag(element, "outside"),
                    _flag(element, "keyframe"),
                )
            )
        tracks.append(sorted(shapes, key=lambda s: s.frame))
    return CvatTask(
        name=task.findtext("name") or "",
        size=size,
        width=_int(task, "original_size/width"),
        height=_int(task, "original_size/height"),
        start_frame=_int(task, "start_frame") or 0,
        frame_filter=(task.findtext("frame_filter") or "").strip(),
        tracks=tracks,
        labels=labels,
    )


def read_export(path: Path) -> CvatTask:
    """Read a CVAT export: the downloaded zip, or the annotations.xml inside it."""
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                return parse_export(z.read("annotations.xml").decode())
        return parse_export(path.read_text())
    except KeyError:
        raise ValueError(f"{path.name} has no annotations.xml") from None
    except ElementTree.ParseError as error:
        raise ValueError(f"{path.name} isn't valid XML: {error}") from None


def _check_fits(task: CvatTask, clip: ClipManifest) -> None:
    if task.name != clip.name:
        raise ValueError(f"the export is for task {task.name!r}, the clip is {clip.name!r}")
    if task.start_frame != 0 or task.frame_filter:
        raise ValueError("the task must use every frame of the clip, with no start frame or step")
    if task.size != len(clip.frames):
        raise ValueError(f"the task has {task.size} frames, the clip has {len(clip.frames)}")
    if task.width is not None and (task.width, task.height) != (clip.width, clip.height):
        raise ValueError(
            f"the task's images are {task.width}x{task.height} pixels, "
            f"the clip's are {clip.width}x{clip.height}"
        )
    wrong = task.labels - {LABEL}
    if wrong:
        raise ValueError(f"unknown label {', '.join(sorted(wrong))}. Label the ball as {LABEL!r}")


def to_ball_labels(task: CvatTask, clip: ClipManifest) -> list[BallLabelRow]:
    """One ball_labels row for every frame of the clip, in frame order."""
    _check_fits(task, clip)
    seen: dict[int, Shape] = {}
    hidden: dict[int, Shape] = {}
    for track in task.tracks:
        for before, after in zip(track, track[1:], strict=False):
            if not before.outside and after.frame != before.frame + 1:
                raise ValueError(
                    f"a track has frames {before.frame} and {after.frame} but is missing those "
                    'between. Export as "CVAT for video 1.1"'
                )
        for shape in track:
            if not 0 <= shape.frame < task.size:
                raise ValueError(f"shape on frame {shape.frame} is outside the task")
            if shape.outside:
                hidden.setdefault(shape.frame, shape)
            elif shape.frame in seen:
                raise ValueError(f"two balls on task frame {shape.frame}. Keep one track a frame")
            else:
                seen[shape.frame] = shape
    rows = []
    for i, (frame, t) in enumerate(zip(clip.frames, clip.t, strict=True)):
        shape = seen.get(i)
        if shape is not None:
            row = BallLabelRow(
                frame=frame,
                t=t,
                x=shape.x,
                y=shape.y,
                visible=True,
                clicked=shape.keyframe,
                split=clip.split,
            )
        else:
            clicked = i in hidden and hidden[i].keyframe
            row = BallLabelRow(
                frame=frame, t=t, x=None, y=None, visible=False, clicked=clicked, split=clip.split
            )
        rows.append(row)
    return rows


def save_labels(rows: list[BallLabelRow], video_id: str, labeller: str, labels: Path) -> Path:
    """Save `rows` merged with the labeller's latest version as a new version.

    Rows from an earlier version on the same frames are replaced, so a fixed clip can be
    converted again. Older versions stay as they are.
    """
    if not re.fullmatch(VIDEO_ID_PATTERN, video_id):
        raise ValueError(f"not a video id: {video_id!r}")
    try:
        TypeAdapter(Handle).validate_python(labeller)
    except ValidationError:
        raise ValueError(
            f"the labeller must be a short lowercase handle, not {labeller!r}"
        ) from None
    folder = labels / BALL_LABELS_FOLDER / video_id / labeller
    merged = {r.frame: r for r in rows}
    previous = store.latest(folder, ".parquet")
    if previous is not None:
        old = BALL_LABELS.rows(BALL_LABELS.read(previous))
        if old and rows and old[0].split != rows[0].split:
            raise ValueError(f"{previous} has split {old[0].split}, the new rows {rows[0].split}")
        merged = {r.frame: r for r in old} | merged
    table = BALL_LABELS.table([merged[f] for f in sorted(merged)])
    errors = BALL_LABELS.errors(table)
    if errors:
        raise ValueError("; ".join(errors))
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    return store.write_new_version(folder, sink.getvalue().to_pybytes(), ".parquet")
