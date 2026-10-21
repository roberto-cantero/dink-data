"""frames.parquet against events.json: the game log's times come from the frame table."""

import pyarrow as pa

from dinkdata.contracts.frames import FRAMES, FrameRow, check_log_frames
from dinkdata.contracts.game_log import EventLog
from tests.contracts.examples import example

STEP = 1 / 30
DROPPED = 14  # The example game log says 14 frames were dropped early on.


def frames_for_example(frames: int = 7000) -> pa.Table:
    """A synthetic frame table for the example events.json: 14 frames lost before frame 100."""
    rows = []
    for frame in range(frames):
        lost = DROPPED if frame >= 100 else 0
        rows.append(
            FrameRow(
                frame=frame,
                t=round((frame + lost) * STEP, 2),
                dropped_before=DROPPED if frame == 100 else 0,
                duplicate=False,
            )
        )
    return FRAMES.table(rows)


def test_example_events_fit_their_frames():
    log = EventLog.model_validate(example("events"))
    frames = frames_for_example()
    assert FRAMES.errors(frames) == []
    assert check_log_frames(log, frames) == []


def test_dropped_frame_count_must_match():
    data = example("events")
    data["video"]["dropped_frames"] = 3
    errors = check_log_frames(EventLog.model_validate(data), frames_for_example())
    assert any("dropped_frames" in e for e in errors)


def test_an_event_time_off_its_frame_is_caught():
    data = example("events")
    data["games"][0]["rallies"][0]["events"][0]["t"] = 184.5
    errors = check_log_frames(EventLog.model_validate(data), frames_for_example())
    assert any("e1" in e for e in errors)


def test_a_frame_past_the_end_is_caught():
    log = EventLog.model_validate(example("events"))
    errors = check_log_frames(log, frames_for_example(frames=6000))
    assert any("past the video's last frame" in e for e in errors)
