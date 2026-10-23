"""ByteTrack: detections linked into tracks by motion, with low-score boxes kept for old tracks."""

import numpy as np

from dinkdata.players.bytetrack import ByteTrack


def box(cx: float, cy: float, w: float = 40, h: float = 100) -> list[float]:
    return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]


def step(tracker: ByteTrack, boxes: list[list[float]], scores: list[float]) -> list[int]:
    return tracker.update(np.array(boxes, dtype=float).reshape(-1, 4), np.array(scores)).tolist()


def test_two_people_walking_keep_their_ids():
    tracker = ByteTrack()
    first = step(tracker, [box(100, 300), box(400, 300)], [0.9, 0.9])
    assert sorted(first) == [1, 2]
    for i in range(1, 20):
        ids = step(tracker, [box(100 + 5 * i, 300), box(400 - 5 * i, 300)], [0.9, 0.9])
        assert ids == first


def test_detections_in_any_order_keep_their_ids():
    tracker = ByteTrack()
    a, b = step(tracker, [box(100, 300), box(400, 300)], [0.9, 0.9])
    assert step(tracker, [box(402, 300), box(102, 300)], [0.9, 0.9]) == [b, a]


def test_a_person_missed_for_a_few_frames_comes_back_with_the_same_id():
    tracker = ByteTrack(max_lost=10)
    pid = -1
    for i in range(5):
        (pid,) = step(tracker, [box(100 + 4 * i, 300)], [0.9])
    for _ in range(3):
        assert step(tracker, [], []) == []
    assert step(tracker, [box(100 + 4 * 8, 300)], [0.9]) == [pid]


def test_a_person_missed_too_long_gets_a_new_id():
    tracker = ByteTrack(max_lost=3)
    (pid,) = step(tracker, [box(100, 300)], [0.9])
    for _ in range(5):
        step(tracker, [], [])
    step(tracker, [box(100, 300)], [0.9])
    (new,) = step(tracker, [box(100, 300)], [0.9])
    assert new != pid


def test_a_low_score_box_continues_a_track_but_starts_none():
    tracker = ByteTrack()
    (pid,) = step(tracker, [box(100, 300)], [0.9])
    assert step(tracker, [box(103, 300), box(500, 300)], [0.3, 0.3]) == [pid, -1]
    assert step(tracker, [box(106, 300), box(500, 300)], [0.3, 0.3]) == [pid, -1]


def test_after_the_first_frame_a_new_track_needs_a_second_sighting():
    tracker = ByteTrack()
    step(tracker, [box(100, 300)], [0.9])
    assert step(tracker, [box(100, 300), box(500, 300)], [0.9, 0.9])[1] == -1
    second = step(tracker, [box(100, 300), box(500, 300)], [0.9, 0.9])[1]
    assert second > 0


def test_boxes_far_apart_never_match():
    tracker = ByteTrack()
    (pid,) = step(tracker, [box(100, 300)], [0.9])
    step(tracker, [box(900, 300)], [0.9])
    (other,) = step(tracker, [box(900, 300)], [0.9])
    assert other != pid
