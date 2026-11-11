"""CVAT ball clicks: clip export, the export parser and the converter to ball_labels."""

import zipfile
from pathlib import Path

import cv2
import pytest

from dinkdata.ball import cvat
from dinkdata.contracts.ball import BALL_LABELS
from dinkdata.video.reader import VideoReader
from tests.fixtures.make_gappy_clip import CUT, HEIGHT, KEPT, WIDTH, read_number

VIDEO_ID = "v_0123456789abcdef"
START = KEPT.index(25)  # the clip runs across the dropped camera frames 30, 31 and 32
COUNT = 15


def point(frame: int, x: float = 10.0, y: float = 20.0, outside: int = 0, keyframe: int = 1):
    return (
        f'<points frame="{frame}" outside="{outside}" occluded="0" keyframe="{keyframe}" '
        f'points="{x:.2f},{y:.2f}" z_order="0"></points>'
    )


def cvat_xml(
    tracks: list[list[str]],
    name: str = f"{VIDEO_ID}_f{START:06d}",
    size: int = COUNT,
    width: int = WIDTH,
    height: int = HEIGHT,
    label: str = "ball",
    frame_filter: str = "",
) -> str:
    """A "CVAT for video 1.1" export, as CVAT writes it for one task."""
    body = "".join(
        f'<track id="{i}" label="{label}" source="manual">{"".join(shapes)}</track>'
        for i, shapes in enumerate(tracks)
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?><annotations><version>1.1</version><meta><task>'
        f"<id>7</id><name>{name}</name><size>{size}</size><mode>interpolation</mode>"
        f"<start_frame>0</start_frame><stop_frame>{size - 1}</stop_frame>"
        f"<frame_filter>{frame_filter}</frame_filter>"
        f"<original_size><width>{width}</width><height>{height}</height>"
        f"</original_size></task></meta>{body}</annotations>"
    )


@pytest.fixture
def clip(gappy_clip: Path, tmp_path: Path) -> cvat.Clip:
    return cvat.export_clip(gappy_clip, VIDEO_ID, "train", START, COUNT, tmp_path / "cvat")


def test_clip_names_images_by_their_real_frame(clip: cvat.Clip):
    names = sorted(p.name for p in clip.folder.glob("*.jpg"))
    assert names == [cvat.image_name(f) for f in range(START, START + COUNT)]
    assert clip.folder.name == f"{VIDEO_ID}_f{START:06d}"
    assert clip.manifest.frames == list(range(START, START + COUNT))
    assert (clip.manifest.width, clip.manifest.height) == (WIDTH, HEIGHT)


def test_clip_refuses_to_overwrite(gappy_clip: Path, clip: cvat.Clip):
    with pytest.raises(ValueError, match="already exists"):
        cvat.export_clip(gappy_clip, VIDEO_ID, "train", START, COUNT, clip.folder.parent)


def test_clip_past_the_end_fails(gappy_clip: Path, tmp_path: Path):
    with pytest.raises(ValueError, match="outside the video"):
        cvat.export_clip(gappy_clip, VIDEO_ID, "train", len(KEPT) - 5, COUNT, tmp_path)


def test_converted_frames_line_up_with_the_video(gappy_clip: Path, clip: cvat.Clip):
    """The ticket's alignment test. CVAT shows task frame i as the i-th image in name order.
    Every converted row must point at that same picture in the video, across dropped frames."""
    assert {30, 31, 32} <= set(CUT)
    flight = [point(i, x=10 + 2 * i, y=20 - i, keyframe=int(i in (0, 10))) for i in range(11)]
    tracks = [[*flight, point(11, outside=1)]]
    labels = cvat.to_ball_labels(cvat.parse_export(cvat_xml(tracks)), clip.manifest)

    images = sorted(clip.folder.glob("*.jpg"))
    assert len(labels) == len(images) == COUNT
    with VideoReader(gappy_clip) as video:
        for task_frame, (row, image) in enumerate(zip(labels, images, strict=True)):
            picture = cv2.imread(str(image))
            assert picture is not None
            shown_in_cvat = read_number(picture[:, :, ::-1])
            frame = video[row.frame]
            assert read_number(frame.image) == shown_in_cvat == KEPT[START + task_frame]
            assert row.t == pytest.approx(frame.t)
    assert KEPT[labels[5].frame] == 33  # the first frame after the three dropped ones


def test_clicked_interpolated_and_hidden_rows(clip: cvat.Clip):
    tracks = [[point(2), point(3, x=11, keyframe=0), point(4, x=12), point(5, outside=1)]]
    rows = cvat.to_ball_labels(cvat.parse_export(cvat_xml(tracks)), clip.manifest)
    by_task = dict(enumerate(rows))
    assert (by_task[2].visible, by_task[2].clicked, by_task[2].x) == (True, True, 10.0)
    assert (by_task[3].visible, by_task[3].clicked, by_task[3].x) == (True, False, 11.0)
    assert (by_task[5].visible, by_task[5].clicked, by_task[5].x) == (False, True, None)
    # A frame no shape covers is hidden, and nobody clicked it.
    assert (by_task[0].visible, by_task[0].clicked) == (False, False)
    assert {r.split for r in rows} == {"train"}
    assert [r.frame for r in rows] == sorted(r.frame for r in rows)


def test_a_new_track_after_an_outside_frame_wins(clip: cvat.Clip):
    tracks = [[point(0), point(1, outside=1)], [point(1, x=50), point(2, outside=1)]]
    rows = cvat.to_ball_labels(cvat.parse_export(cvat_xml(tracks)), clip.manifest)
    assert (rows[1].visible, rows[1].x) == (True, 50.0)


@pytest.mark.parametrize(
    ("xml", "message"),
    [
        pytest.param(cvat_xml([], size=COUNT - 1), "frames", id="size"),
        pytest.param(cvat_xml([], width=WIDTH * 2), "pixels", id="image size"),
        pytest.param(cvat_xml([], name="other_task"), "task", id="task name"),
        pytest.param(cvat_xml([[point(0)]], label="player"), "label", id="label"),
        pytest.param(cvat_xml([[point(0)], [point(0, x=40)]]), "two balls", id="two balls"),
        pytest.param(cvat_xml([[point(COUNT)]]), "outside the task", id="frame past end"),
        pytest.param(cvat_xml([], frame_filter="step=2"), "every frame", id="step"),
    ],
)
def test_rejects_an_export_that_does_not_fit_the_clip(clip: cvat.Clip, xml: str, message: str):
    with pytest.raises(ValueError, match=message):
        cvat.to_ball_labels(cvat.parse_export(xml), clip.manifest)


def test_rejects_a_track_with_missing_frames(clip: cvat.Clip):
    """CVAT writes every frame of a track. A gap would turn frames it filled into hidden ones."""
    with pytest.raises(ValueError, match="missing"):
        cvat.to_ball_labels(cvat.parse_export(cvat_xml([[point(0), point(4)]])), clip.manifest)


def test_rejects_a_shape_with_two_points():
    xml = cvat_xml([[point(0).replace('points="10.00,20.00"', 'points="1,2;3,4"')]])
    with pytest.raises(ValueError, match="one point"):
        cvat.parse_export(xml)


def test_reads_annotations_from_a_cvat_zip(tmp_path: Path):
    path = tmp_path / "export.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("annotations.xml", cvat_xml([[point(0)]]))
    assert cvat.read_export(path).size == COUNT


def test_save_merges_clips_into_a_new_version(gappy_clip: Path, clip: cvat.Clip, tmp_path: Path):
    labels = tmp_path / "labels"
    first = cvat.to_ball_labels(cvat.parse_export(cvat_xml([[point(0)]])), clip.manifest)
    v1 = cvat.save_labels(first, VIDEO_ID, "robby", labels)
    later = cvat.export_clip(gappy_clip, VIDEO_ID, "train", 0, 10, tmp_path / "cvat")
    xml = cvat_xml([[point(1)]], name=later.folder.name, size=10)
    second = cvat.to_ball_labels(cvat.parse_export(xml), later.manifest)
    v2 = cvat.save_labels(second, VIDEO_ID, "robby", labels)

    assert v1.name == "v1.parquet" and v2.name == "v2.parquet"
    assert v1.parent == labels / "ball" / VIDEO_ID / "robby"
    assert len(BALL_LABELS.read(v1)) == COUNT
    assert len(BALL_LABELS.read(v2)) == COUNT + 10


def test_a_fixed_clip_replaces_its_own_rows(clip: cvat.Clip, tmp_path: Path):
    labels = tmp_path / "labels"
    old = cvat.to_ball_labels(cvat.parse_export(cvat_xml([[point(0)]])), clip.manifest)
    cvat.save_labels(old, VIDEO_ID, "robby", labels)
    fixed = cvat.to_ball_labels(cvat.parse_export(cvat_xml([[point(0, x=99)]])), clip.manifest)
    v2 = cvat.save_labels(fixed, VIDEO_ID, "robby", labels)
    rows = BALL_LABELS.rows(BALL_LABELS.read(v2))
    assert len(rows) == COUNT
    assert rows[0].x == 99.0


def test_save_refuses_a_different_split(clip: cvat.Clip, tmp_path: Path):
    labels = tmp_path / "labels"
    rows = cvat.to_ball_labels(cvat.parse_export(cvat_xml([[point(0)]])), clip.manifest)
    cvat.save_labels(rows, VIDEO_ID, "robby", labels)
    other = [r.model_copy(update={"split": "test"}) for r in rows]
    with pytest.raises(ValueError, match="split"):
        cvat.save_labels(other, VIDEO_ID, "robby", labels)


def test_cli_clip_then_convert(gappy_clip: Path, tmp_path: Path):
    from typer.testing import CliRunner

    from dinkdata.cli import app

    runner = CliRunner()
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / f"{VIDEO_ID}.mp4").write_bytes(gappy_clip.read_bytes())
    out = tmp_path / "cvat"
    result = runner.invoke(
        app,
        ["ball", "clip", VIDEO_ID, "--start", str(START), "--count", str(COUNT),
         "--split", "train", "--videos", str(videos), "--out", str(out)],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    folder = out / f"{VIDEO_ID}_f{START:06d}"
    assert f"Name the CVAT task {folder.name}" in result.output

    export = tmp_path / "export.zip"
    with zipfile.ZipFile(export, "w") as z:
        shapes = [point(0), point(1, keyframe=0), point(2, x=15), point(3, outside=1)]
        z.writestr("annotations.xml", cvat_xml([shapes]))
    labels = tmp_path / "labels"
    args = ["ball", "convert", str(folder), str(export), "--labeller", "robby"]
    result = runner.invoke(app, [*args, "--labels", str(labels)])
    assert result.exit_code == 0, result.output
    assert f"{COUNT} frames: 3 with the ball, 3 clicked." in result.output
    assert (labels / "ball" / VIDEO_ID / "robby" / "v1.parquet").is_file()


def test_cli_convert_reports_a_mismatch(clip: cvat.Clip, tmp_path: Path):
    from typer.testing import CliRunner

    from dinkdata.cli import app

    export = tmp_path / "annotations.xml"
    export.write_text(cvat_xml([], size=3))
    result = CliRunner().invoke(
        app, ["ball", "convert", str(clip.folder), str(export), "--labeller", "robby",
              "--labels", str(tmp_path / "labels")],
    )  # fmt: skip
    assert result.exit_code == 1
    assert "the task has 3 frames" in result.output
