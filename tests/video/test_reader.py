"""The video reader: every frame with its index and time, in order and by exact random access."""

import random

import numpy as np
import pyarrow as pa
import pytest

from dinkdata.contracts.frames import FRAMES, FrameRow
from dinkdata.video.reader import VideoReader
from tests.fixtures.make_gappy_clip import CUT, HEIGHT, KEPT, WIDTH, camera_t, read_number


def frames_table(times: list[float]) -> pa.Table:
    return FRAMES.table(
        [FrameRow(frame=i, t=t, dropped_before=0, duplicate=False) for i, t in enumerate(times)]
    )


def test_times_come_from_timestamps_with_the_gaps(gappy_clip):
    with VideoReader(gappy_clip) as video:
        assert len(video) == len(KEPT)
        assert video.times == pytest.approx([camera_t(n) for n in KEPT])
        assert video.times[KEPT.index(11)] == pytest.approx(11 / 30)


def test_reading_in_order_returns_every_frame(gappy_clip):
    with VideoReader(gappy_clip) as video:
        frames = list(video)
    assert [f.index for f in frames] == list(range(len(KEPT)))
    assert [read_number(f.image) for f in frames] == KEPT
    assert [f.t for f in frames] == pytest.approx([camera_t(n) for n in KEPT])
    assert frames[0].image.shape == (HEIGHT, WIDTH, 3)
    assert frames[0].image.dtype == np.uint8


def test_random_access_returns_the_exact_frame_in_any_order(gappy_clip):
    order = list(range(len(KEPT)))
    random.Random(40).shuffle(order)
    with VideoReader(gappy_clip) as video:
        for index in order:
            frame = video[index]
            assert frame.index == index
            assert read_number(frame.image) == KEPT[index]
            assert frame.t == pytest.approx(camera_t(KEPT[index]))


@pytest.mark.parametrize("number", [0, 9, 11, 12, 13, 29, 33, 59])
def test_random_access_around_keyframes_and_gaps(gappy_clip, number):
    """11 and 12 come right after a dropped frame and decode after the keyframe at 13, so a
    seek to their time alone lands on 13. 33 comes right after three dropped frames."""
    assert 10 in CUT and 32 in CUT
    with VideoReader(gappy_clip) as video:
        video[len(KEPT) - 1]  # leave the decoder somewhere else first
        assert read_number(video[KEPT.index(number)].image) == number


def test_reading_a_slice_in_order(gappy_clip):
    start, stop = KEPT.index(11), KEPT.index(36)
    with VideoReader(gappy_clip) as video:
        frames = list(video.iter_frames(start, stop))
    assert [f.index for f in frames] == list(range(start, stop))
    assert [read_number(f.image) for f in frames] == KEPT[start:stop]


def test_reading_to_the_end_from_the_middle(gappy_clip):
    with VideoReader(gappy_clip) as video:
        frames = list(video.iter_frames(len(KEPT) - 3))
    assert [read_number(f.image) for f in frames] == KEPT[-3:]


def test_bgr_pictures_for_opencv(gappy_clip):
    with VideoReader(gappy_clip, fmt="bgr24") as video:
        assert read_number(video[5].image[:, :, ::-1]) == KEPT[5]


@pytest.mark.parametrize("index", [-1, len(KEPT)])
def test_an_index_outside_the_video_is_an_error(gappy_clip, index):
    with VideoReader(gappy_clip) as video, pytest.raises(IndexError):
        video[index]


@pytest.mark.parametrize(("start", "stop"), [(-1, None), (0, len(KEPT) + 1), (5, 4)])
def test_a_slice_outside_the_video_is_an_error(gappy_clip, start, stop):
    with VideoReader(gappy_clip) as video, pytest.raises(IndexError):
        list(video.iter_frames(start, stop))


def test_a_matching_frames_table_is_accepted(gappy_clip):
    table = frames_table([camera_t(n) for n in KEPT])
    with VideoReader(gappy_clip, frames=table) as video:
        assert len(video) == len(KEPT)


def test_a_frames_table_with_another_count_is_rejected(gappy_clip):
    table = frames_table([camera_t(n) for n in KEPT[:-1]])
    with pytest.raises(ValueError, match="frames"):
        VideoReader(gappy_clip, frames=table)


def test_a_frames_table_with_another_time_is_rejected(gappy_clip):
    times = [camera_t(n) for n in KEPT]
    times[20] += 0.01
    with pytest.raises(ValueError, match="frame 20"):
        VideoReader(gappy_clip, frames=frames_table(times))


def test_an_opencv_clip_without_gaps_reads_evenly(synthetic_clip):
    with VideoReader(synthetic_clip) as video:
        assert len(video) == 60
        assert np.diff(video.times) == pytest.approx(np.full(59, 1 / 30))
        assert video[59].index == 59


def test_a_closed_reader_cannot_read(gappy_clip):
    video = VideoReader(gappy_clip)
    video.close()
    with pytest.raises(ValueError, match="closed"):
        video[0]
