"""ByteTrack (Zhang et al., ECCV 2022): link person boxes into tracks by motion alone.

Each track has a constant-velocity Kalman filter on the box centre, aspect ratio and height, as
in SORT and DeepSORT. Every step matches tracks to boxes by IoU in two rounds. High-score boxes
go first, to every track, including recently lost ones. Low-score boxes, often people half
hidden behind another player or the net, then go to the tracks still unmatched, so a track
survives an occlusion without low-score boxes starting tracks of their own. A new track needs a
second sighting before it gets an id, except on the first step.

Steps count calls to `update`, so `max_lost` is in steps, not seconds.
"""

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

HIGH_SCORE = 0.5
LOW_SCORE = 0.1
NEW_TRACK_SCORE = 0.6
FIRST_MAX_COST = 0.8
SECOND_MAX_COST = 0.5
UNCONFIRMED_MAX_COST = 0.7
"""Largest 1 - IoU accepted in each round, as in the paper's code."""

STD_POSITION = 1 / 20
STD_VELOCITY = 1 / 160
"""Kalman noise as shares of the box height, from DeepSORT."""

_F = np.eye(8)
_F[:4, 4:] = np.eye(4)
_H = np.eye(4, 8)


def _to_xyah(box: np.ndarray) -> np.ndarray:
    x1, y1, x2, y2 = box
    h = max(y2 - y1, 1e-6)
    return np.array([(x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) / h, h])


def _to_box(xyah: np.ndarray) -> np.ndarray:
    cx, cy, a, h = xyah[:4]
    w = a * h
    return np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])


@dataclass
class _Track:
    id: int
    mean: np.ndarray
    cov: np.ndarray
    last_step: int
    confirmed: bool
    lost: bool = False

    @classmethod
    def start(cls, track_id: int, box: np.ndarray, step: int, confirmed: bool) -> "_Track":
        z = _to_xyah(box)
        h = z[3]
        std = [
            *(2 * STD_POSITION * h, 2 * STD_POSITION * h, 1e-2, 2 * STD_POSITION * h),
            *(10 * STD_VELOCITY * h, 10 * STD_VELOCITY * h, 1e-5, 10 * STD_VELOCITY * h),
        ]
        mean = np.concatenate([z, np.zeros(4)])
        return cls(track_id, mean, np.diag(np.square(std)), step, confirmed)

    def predict(self) -> None:
        if self.lost:  # as in the reference code, a lost box keeps its size
            self.mean[7] = 0.0
        h = self.mean[3]
        std = [
            *(STD_POSITION * h, STD_POSITION * h, 1e-2, STD_POSITION * h),
            *(STD_VELOCITY * h, STD_VELOCITY * h, 1e-5, STD_VELOCITY * h),
        ]
        self.mean = _F @ self.mean
        self.cov = _F @ self.cov @ _F.T + np.diag(np.square(std))

    def correct(self, box: np.ndarray, step: int) -> None:
        h = self.mean[3]
        noise = np.diag(np.square([STD_POSITION * h, STD_POSITION * h, 1e-1, STD_POSITION * h]))
        s = _H @ self.cov @ _H.T + noise
        gain = np.linalg.solve(s, _H @ self.cov).T
        self.mean = self.mean + gain @ (_to_xyah(box) - _H @ self.mean)
        self.cov = self.cov - gain @ s @ gain.T
        self.last_step = step
        self.lost = False

    @property
    def box(self) -> np.ndarray:
        return _to_box(self.mean)


def iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU of every box in `a` with every box in `b`, both n x 4 as x1, y1, x2, y2."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(area_a[:, None] + area_b[None, :] - inter, 1e-9)


def _match(
    tracks: list[_Track], boxes: np.ndarray, max_cost: float
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Hungarian matching on 1 - IoU. Returns pairs and the unmatched track and box indices."""
    if not tracks or len(boxes) == 0:
        return [], list(range(len(tracks))), list(range(len(boxes)))
    cost = 1 - iou(np.stack([t.box for t in tracks]), boxes)
    rows, cols = linear_sum_assignment(cost)
    pairs = [(int(r), int(c)) for r, c in zip(rows, cols, strict=True) if cost[r, c] <= max_cost]
    matched_t = {r for r, _ in pairs}
    matched_b = {c for _, c in pairs}
    return (
        pairs,
        [i for i in range(len(tracks)) if i not in matched_t],
        [j for j in range(len(boxes)) if j not in matched_b],
    )


class ByteTrack:
    def __init__(self, max_lost: int = 30) -> None:
        self.max_lost = max_lost
        self._tracks: list[_Track] = []
        self._next_id = 1
        self._step = 0

    def update(self, boxes: np.ndarray, scores: np.ndarray) -> np.ndarray:
        """Track ids for one step's boxes (n x 4, x1, y1, x2, y2) and scores (n).

        A box gets -1 when it belongs to no track, or only to one not yet confirmed.
        """
        boxes = np.asarray(boxes, dtype=np.float64).reshape(-1, 4)
        scores = np.asarray(scores, dtype=np.float64)
        ids = np.full(len(boxes), -1, dtype=np.int64)
        step = self._step
        high = np.flatnonzero(scores >= HIGH_SCORE)
        low = np.flatnonzero((scores >= LOW_SCORE) & (scores < HIGH_SCORE))

        for track in self._tracks:
            track.predict()
        confirmed = [t for t in self._tracks if t.confirmed]
        unconfirmed = [t for t in self._tracks if not t.confirmed]

        pairs, left_tracks, left_high = _match(confirmed, boxes[high], FIRST_MAX_COST)
        for ti, bi in pairs:
            confirmed[ti].correct(boxes[high[bi]], step)
            ids[high[bi]] = confirmed[ti].id

        still_tracked = [confirmed[i] for i in left_tracks if not confirmed[i].lost]
        pairs, unmatched, _ = _match(still_tracked, boxes[low], SECOND_MAX_COST)
        for ti, bi in pairs:
            still_tracked[ti].correct(boxes[low[bi]], step)
            ids[low[bi]] = still_tracked[ti].id
        for i in unmatched:
            still_tracked[i].lost = True

        rest = high[left_high]
        pairs, dropped, left_rest = _match(unconfirmed, boxes[rest], UNCONFIRMED_MAX_COST)
        for ti, bi in pairs:
            unconfirmed[ti].correct(boxes[rest[bi]], step)
            unconfirmed[ti].confirmed = True
            ids[rest[bi]] = unconfirmed[ti].id
        gone = {id(unconfirmed[i]) for i in dropped}

        for bi in rest[left_rest]:
            if scores[bi] < NEW_TRACK_SCORE:
                continue
            track = _Track.start(self._next_id, boxes[bi], step, confirmed=step == 0)
            self._next_id += 1
            self._tracks.append(track)
            if track.confirmed:
                ids[bi] = track.id

        self._tracks = [
            t for t in self._tracks if id(t) not in gone and step - t.last_step <= self.max_lost
        ]
        self._step += 1
        return ids
