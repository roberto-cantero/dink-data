"""Read a video's frames with their index and time, in order or by exact random access.

The index of a frame is its place among the decoded frames in display order. Its time comes
from its presentation timestamp (PTS) through `contracts.common.t_from_pts`, never from a frame
rate, because PickleCam videos drop frames (ADR 0005). The reader lists every packet's PTS
when it opens the file, which needs no decoding. These are the same frames, in the same order,
that `dink ingest` writes to frames.parquet from ffprobe.

A seek in FFmpeg lands near a keyframe, not on the frame asked for, and for an MP4 it can land
on a keyframe after it. So random access seeks, then decodes forward until the frame's PTS is
the one wanted. A frame counts only if a keyframe at or before it was decoded first. Otherwise
it may be a B-frame drawn without its references, and the reader seeks to an earlier keyframe.
"""

import bisect
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from types import TracebackType

import av
import numpy as np
import pyarrow as pa

from dinkdata.contracts.common import t_from_pts
from dinkdata.contracts.tables import column

TOLERANCE = 1e-3
"""Seconds a frames.parquet time may differ from the video's, as in `check_log_frames`."""


@dataclass(frozen=True)
class VideoFrame:
    """One decoded frame."""

    index: int
    """0-based index among the decoded frames, the `frame` of every contract."""
    t: float
    """Seconds from the first frame's timestamp."""
    image: np.ndarray
    """Height x width x 3, uint8, in the reader's pixel format (RGB unless asked)."""


class VideoReader:
    """Frames of a video file's first video stream. Use it as a context manager.

    `frames` is the video's frames.parquet table. When given, the reader checks that it lists
    the same frames at the same times. `fmt` is the pixel format: "rgb24", or "bgr24" for
    OpenCV.
    """

    def __init__(self, path: Path, frames: pa.Table | None = None, fmt: str = "rgb24") -> None:
        self._fmt = fmt
        self._container = av.open(str(path))
        try:
            self._stream = self._container.streams.video[0]
            self._stream.thread_type = "AUTO"
            self._pts, self._keyframes = self._index()
            if self._stream.time_base is None:
                raise ValueError(f"{path.name} has no time base")
            # PyAV gives its own rational type. Fraction keeps t exactly as ingest computes it.
            time_base = Fraction(self._stream.time_base.num, self._stream.time_base.den)
            self.times = np.array([t_from_pts(p, self._pts[0], time_base) for p in self._pts])
            """Seconds from the first frame, for every frame index."""
            if frames is not None:
                self._check(frames)
        except BaseException:
            self._container.close()
            raise
        self._closed = False

    def _index(self) -> tuple[list[int], list[int]]:
        """Every frame's PTS and every keyframe's PTS, each sorted into display order."""
        pts, keyframes = [], []
        for packet in self._container.demux(self._stream):
            if packet.size == 0:  # the empty packet that ends the stream
                continue
            if packet.pts is None:
                raise ValueError("a video packet has no timestamp")
            pts.append(packet.pts)
            if packet.is_keyframe:
                keyframes.append(packet.pts)
        if not pts:
            raise ValueError("the video has no frames")
        pts.sort()
        if any(a == b for a, b in zip(pts, pts[1:], strict=False)):
            raise ValueError("two video frames share a timestamp")
        if not keyframes or min(keyframes) != pts[0]:
            raise ValueError("the video doesn't start with a keyframe")
        return pts, sorted(keyframes)

    def _check(self, frames: pa.Table) -> None:
        t = column(frames, "t")
        if len(t) != len(self):
            raise ValueError(f"frames.parquet lists {len(t)} frames, the video has {len(self)}")
        wrong = np.flatnonzero(np.abs(t - self.times) > TOLERANCE)
        if len(wrong):
            i = int(wrong[0])
            raise ValueError(
                f"frames.parquet gives frame {i} t {t[i]}, the video gives {self.times[i]}"
            )

    def __len__(self) -> int:
        return len(self._pts)

    def __getitem__(self, index: int) -> VideoFrame:
        """The frame at `index`, exactly."""
        if not 0 <= index < len(self):
            raise IndexError(f"frame {index} is outside the video's {len(self)} frames")
        return next(self.iter_frames(index, index + 1))

    def __iter__(self) -> Iterator[VideoFrame]:
        return self.iter_frames()

    def iter_frames(self, start: int = 0, stop: int | None = None) -> Iterator[VideoFrame]:
        """Frames `start` up to but not including `stop`, in order. `stop` defaults to the end."""
        stop = len(self) if stop is None else stop
        if not 0 <= start < stop <= len(self):
            raise IndexError(f"frames {start} to {stop} are outside the video's {len(self)}")
        decoded = self._decode_from(start)
        for index in range(start, stop):
            frame = next(decoded, None)
            if frame is None or frame.pts != self._pts[index]:
                got = "the end" if frame is None else f"pts {frame.pts}"
                raise RuntimeError(f"frame {index} should have pts {self._pts[index]}, got {got}")
            image = frame.to_ndarray(format=self._fmt)
            yield VideoFrame(index=index, t=float(self.times[index]), image=image)

    def _decode_from(self, index: int) -> Iterator[av.VideoFrame]:
        """Decoded frames from `index` on, after a seek that decodes it from its keyframe."""
        if self._closed:
            raise ValueError("the video reader is closed")
        target = self._pts[index]
        # Keyframes at or before the target, nearest first. A seek to the nearest one usually
        # works, and each retry starts from the keyframe before.
        before = self._keyframes[: bisect.bisect_right(self._keyframes, target)]
        for offset in [target, *reversed(before)]:
            self._container.seek(offset, backward=True, stream=self._stream)
            decoded = self._container.decode(self._stream)
            keyframe_seen = False
            for frame in decoded:
                if frame.pts is None or frame.pts > target:
                    break
                keyframe_seen = keyframe_seen or frame.key_frame
                if frame.pts == target and keyframe_seen:
                    yield frame
                    yield from decoded
                    return
        raise RuntimeError(f"frame {index} (pts {target}) can't be decoded")

    def close(self) -> None:
        if not self._closed:
            self._container.close()
            self._closed = True

    def __enter__(self) -> "VideoReader":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
