"""Exact frames for the events page, as JPEG pictures by frame index.

Browsers can't land on an exact frame, so the page asks the server for each one. The video
reader (`dinkdata.video.reader`) decodes the frame whose timestamp matches its index. Stepping
forward is the usual move, so the source keeps its decoder open and decodes on from the last
frame instead of seeking again, and it keeps recent pictures to step back through.

Pictures are encoded with PyAV's MJPEG encoder, not OpenCV, so the studio never loads both
copies of FFmpeg (docs/KNOWN-ISSUES.md, K2).
"""

import threading
from collections import OrderedDict
from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path

import av
import pyarrow as pa

from dinkdata.video.reader import VideoFrame, VideoReader

QSCALE = 3
"""MJPEG quality, 2 (best) to 31. 3 gives a 1080p frame of about 200 KB in under 10 ms."""
CACHE = 240
"""Pictures kept: about 8 s of video, and about 50 MB at 1080p."""
AHEAD = 30
"""A frame up to this far after the decoder's position is decoded on to, not sought."""
BACK = 8
"""A seek starts this many frames early, so the next few steps back are already cached."""


class FrameSource:
    """Pictures of a video's frames. Requests come from several threads, so one lock guards
    the decoder."""

    def __init__(self, video: Path, frames: pa.Table) -> None:
        self._reader = VideoReader(video, frames)
        try:
            self.times = [float(t) for t in self._reader.times]
            """Seconds from the first frame, for every frame index."""
            first = self._reader[0]
            self.height, self.width = first.image.shape[:2]
            self.fps_nominal = _nominal_rate(video)
        except BaseException:
            self._reader.close()
            raise
        self._lock = threading.Lock()
        self._cache: OrderedDict[int, bytes] = OrderedDict()
        self._decoder: Iterator[VideoFrame] | None = None
        self._next = 0

    def __len__(self) -> int:
        return len(self.times)

    def jpeg(self, index: int) -> bytes:
        """The picture of frame `index`, exactly."""
        if not 0 <= index < len(self):
            raise IndexError(f"frame {index} is outside the video's {len(self)} frames")
        with self._lock:
            if index in self._cache:
                self._cache.move_to_end(index)
                return self._cache[index]
            if self._decoder is None or not self._next <= index <= self._next + AHEAD:
                start = max(0, index - BACK)
                self._decoder = self._reader.iter_frames(start)
                self._next = start
            try:
                while self._next <= index:
                    frame = next(self._decoder)
                    self._keep(frame.index, _encode(frame))
                    self._next = frame.index + 1
            except BaseException:
                self._decoder = None  # the next request seeks again
                raise
            return self._cache[index]

    def _keep(self, index: int, data: bytes) -> None:
        self._cache[index] = data
        self._cache.move_to_end(index)
        while len(self._cache) > CACHE:
            self._cache.popitem(last=False)

    def close(self) -> None:
        with self._lock:
            self._decoder = None
            self._reader.close()


def _encode(frame: VideoFrame) -> bytes:
    height, width = frame.image.shape[:2]
    codec = av.CodecContext.create("mjpeg", "w")
    codec.width, codec.height, codec.pix_fmt = width, height, "yuvj420p"
    codec.time_base = Fraction(1, 1)
    codec.options = {"qmin": str(QSCALE), "qmax": str(QSCALE)}
    picture = av.VideoFrame.from_ndarray(frame.image, format="rgb24").reformat(format="yuvj420p")
    data = b"".join(bytes(p) for p in [*codec.encode(picture), *codec.encode(None)])
    if not data.startswith(b"\xff\xd8"):
        raise RuntimeError(f"frame {frame.index} couldn't be encoded")
    return data


def _nominal_rate(video: Path) -> float:
    """The container's frame rate, for `video.fps_nominal`. Never used for time."""
    with av.open(str(video)) as container:
        rate = container.streams.video[0].average_rate
    if rate is None or rate <= 0:
        raise ValueError(f"{video.name} has no frame rate")
    return float(rate)
