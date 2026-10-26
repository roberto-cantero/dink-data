"""The M0 player spike (#47): partner identity at the serve, on hand-labelled serves.

    uv run python scripts/player_spike.py court   --out DIR VIDEO_ID...  draw the floor mapping
    uv run python scripts/player_spike.py extract --out DIR VIDEO_ID...  run the models per game
    uv run python scripts/player_spike.py score   --out DIR              print the accuracy table

Every step reads videos from `--videos`, rally-level gold from `--labels` and hand-marked court
points from `DIR/courts.json`, and writes only inside DIR, which must be outside the repo. The
court points stand in for a calibration until `dinkdata.court` exists: rows of court x, court
y, image x and image y, fitted as a homography with one radial lens term.

`extract` samples each labelled game every `STEP` seconds of frame time. It finds people with
RF-DETR, keypoints with RTMPose and the foot point, keeps people whose foot is on our court,
tracks them with ByteTrack and saves colour and DINOv2 features per person. `score` measures
partner identity at every serve after each team's first (`dinkdata.players.serve_check`).
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import cv2
import numpy as np
from scipy.optimize import least_squares

from dinkdata.contracts.common import PlayerId, load, team_of
from dinkdata.contracts.rallies import LabelGame, RallyLabels, upgrade_v1
from dinkdata.court import zones
from dinkdata.court.zones import Half
from dinkdata.players.appearance import colour_feature
from dinkdata.players.bytetrack import ByteTrack
from dinkdata.players.foot import foot_point
from dinkdata.players.models import DinoEmbedder, PersonDetector, RTMPose
from dinkdata.players.serve_check import (
    PARTNER,
    GoldServe,
    ProfileMethod,
    ServeResult,
    Sighting,
    check_game,
    nearest_two,
    on_court,
    serving_half,
    split_server,
    summarise,
    team_a_half,
)
from dinkdata.video.reader import VideoReader

STEP = 0.1
"""Seconds of frame time between sampled frames."""

MAX_LOST = 30
"""Steps a lost track is kept, 3 seconds at `STEP`."""

COARSE_MARGIN = 15.0
"""Feet around the court within which a box-bottom point gets a pose, before the real filter."""

WINDOW = (-1.0, -0.15)
"""Seconds around the serve hit in which the players stand in formation."""

LOG_EVERY = 600
"""Sampled frames between progress lines."""

SOURCES = {"ankles": 0, "box": 1, "hips": 2}


# Floor mapping -------------------------------------------------------------------------------


@dataclass
class FloorMap:
    h: np.ndarray
    k1: float
    centre: np.ndarray
    norm: float

    def _undistort(self, px: np.ndarray) -> np.ndarray:
        d = (px - self.centre) / self.norm
        return self.centre + (px - self.centre) * (1 + self.k1 * (d**2).sum(axis=1, keepdims=True))

    def to_court(self, px: np.ndarray) -> np.ndarray:
        u = self._undistort(np.asarray(px, dtype=np.float64).reshape(-1, 2))
        hom = np.c_[u, np.ones(len(u))] @ self.h.T
        return hom[:, :2] / hom[:, 2:]

    def to_image(self, ft: np.ndarray) -> np.ndarray:
        ft = np.asarray(ft, dtype=np.float64).reshape(-1, 2)
        hom = np.c_[ft, np.ones(len(ft))] @ np.linalg.inv(self.h).T
        u = hom[:, :2] / hom[:, 2:]
        px = u.copy()
        for _ in range(20):  # invert the radial term by fixed-point iteration
            d = (px - self.centre) / self.norm
            px = self.centre + (u - self.centre) / (1 + self.k1 * (d**2).sum(axis=1, keepdims=True))
        return px


def fit_floor(rows: list[list[float]], width: int, height: int) -> tuple[FloorMap, float]:
    """The floor mapping through the hand-marked points, and its RMS error in feet."""
    pts = np.array(rows, dtype=np.float64)
    court, px = pts[:, :2], pts[:, 2:]
    h0, _ = cv2.findHomography(px, court)
    centre, norm = np.array([width / 2, height / 2]), float(width)

    def build(p: np.ndarray) -> FloorMap:
        return FloorMap(np.append(p[1:], 1.0).reshape(3, 3), float(p[0]), centre, norm)

    def residual(p: np.ndarray) -> np.ndarray:
        return (build(p).to_court(px) - court).ravel()

    fit = least_squares(residual, np.r_[0.0, (h0 / h0[2, 2]).ravel()[:8]])
    floor = build(fit.x)
    return floor, float(np.sqrt(np.mean((floor.to_court(px) - court) ** 2) * 2))


def court_lines() -> list[np.ndarray]:
    n = np.linspace(0, 1, 40)[:, None]
    w, length, cx = zones.WIDTH, zones.LENGTH, zones.CENTRE_X
    far_k, near_k = zones.FAR_KITCHEN_Y, zones.NEAR_KITCHEN_Y
    lines = [((0, 0), (0, length)), ((w, 0), (w, length))]
    lines += [((0, y), (w, y)) for y in (0, far_k, zones.NET_Y, near_k, length)]
    lines += [((cx, 0), (cx, far_k)), ((cx, near_k), (cx, length))]
    return [np.array(a) + n * (np.array(b) - np.array(a)) for a, b in lines]


# Inputs --------------------------------------------------------------------------------------


def read_labels(folder: Path, video_id: str) -> RallyLabels:
    """The latest version from the first labeller of a video, upgraded to v2."""
    labeller = sorted(p for p in (folder / video_id).iterdir() if p.is_dir())[0]
    latest = max(labeller.glob("v*.json"), key=lambda p: int(p.stem[1:]))
    data = json.loads(latest.read_text())
    if data.get("schema") == "dinkdata.rallies/v1":
        return upgrade_v1(data)
    return load(RallyLabels, latest)


def courts(out: Path) -> dict[str, list[list[float]]]:
    return json.loads((out / "courts.json").read_text())


# Extract -------------------------------------------------------------------------------------


def sampled(times: np.ndarray, start: float, end: float) -> list[int]:
    """Frame indices between two times, at least `STEP` seconds apart by their timestamps."""
    picked: list[int] = []
    for i in range(int(np.searchsorted(times, start)), int(np.searchsorted(times, end))):
        if not picked or times[i] - times[picked[-1]] >= STEP - 1e-6:
            picked.append(i)
    return picked


def extract_game(
    video: VideoReader,
    game: LabelGame,
    floor: FloorMap,
    models: tuple[PersonDetector, RTMPose, DinoEmbedder],
    log: Callable[[str], None],
) -> dict[str, Any] | None:
    """Per-person columns for one game, or None when no frame or no player was found."""
    detector, posenet, dino = models
    frames = sampled(video.times, game.start_t + WINDOW[0] - 1, game.end_t)
    if not frames:
        log(f"  {game.id}: no frames between {game.start_t:.0f} and {game.end_t:.0f} s")
        return None
    wanted = set(frames)
    tracker = ByteTrack(max_lost=MAX_LOST)
    cols: dict[str, list[Any]] = defaultdict(list)
    done = 0
    for frame in video.iter_frames(frames[0], frames[-1] + 1):
        if frame.index not in wanted:
            continue
        done += 1
        image = frame.image
        height = image.shape[0]
        det = detector(image)
        bottoms = np.c_[(det.boxes[:, 0] + det.boxes[:, 2]) / 2, det.boxes[:, 3]]
        near = (
            [
                -COARSE_MARGIN <= x <= zones.WIDTH + COARSE_MARGIN
                and -COARSE_MARGIN <= y <= zones.LENGTH + COARSE_MARGIN
                for x, y in floor.to_court(bottoms)
            ]
            if len(det.boxes)
            else []
        )
        boxes, conf = det.boxes[np.array(near, dtype=bool)], det.conf[np.array(near, dtype=bool)]
        kps = posenet(image, boxes)
        keep, feet = [], []
        for i in range(len(boxes)):
            fp = foot_point(boxes[i], kps[i], float(conf[i]), height)
            if fp is None:
                continue
            x, y = floor.to_court(np.array([[fp.x, fp.y]]))[0]
            if on_court(x, y):
                keep.append(i)
                feet.append((fp, x, y))
        keep_idx = np.array(keep, dtype=int)
        ids = tracker.update(boxes[keep_idx], conf[keep_idx])
        dinos = dino(image, boxes[keep_idx])
        for j, i in enumerate(keep):
            fp, x, y = feet[j]
            cols["frame"].append(np.int64(frame.index))
            cols["t"].append(np.float64(frame.t))
            cols["track"].append(np.int64(ids[j]))
            cols["box"].append(boxes[i])
            cols["conf"].append(np.float32(conf[i]))
            cols["kps"].append(kps[i])
            cols["foot_px"].append(np.array([fp.x, fp.y], dtype=np.float32))
            cols["foot_ft"].append(np.array([x, y], dtype=np.float32))
            cols["foot_conf"].append(np.float32(fp.conf))
            cols["source"].append(np.int8(SOURCES[fp.source]))
            cols["colour"].append(colour_feature(image, boxes[i], kps[i]))
            cols["dino"].append(dinos[j])
        if done % LOG_EVERY == 0:
            log(f"  {game.id}: t {frame.t:.0f} of {game.end_t:.0f} s")
    if not cols:
        log(f"  {game.id}: nobody on the court")
        return None
    return {k: np.stack(v) for k, v in cols.items()}


def cmd_extract(args: argparse.Namespace) -> None:
    pts = courts(args.out)
    models = (PersonDetector(size=args.size), RTMPose(), DinoEmbedder())
    for video_id in args.video_ids:
        labels = read_labels(args.labels, video_id)
        with VideoReader(args.videos / f"{video_id}.mp4") as video:
            h, w = video[0].image.shape[:2]
            floor, rms = fit_floor(pts[video_id], w, h)
            print(f"{video_id}: floor mapping RMS {rms:.2f} ft", flush=True)
            for game in labels.games:
                target = args.out / f"{video_id}_{game.id}.npz"
                if target.exists():
                    print(f"  {target.name} exists, skipped", flush=True)
                    continue
                data = extract_game(video, game, floor, models, lambda s: print(s, flush=True))
                if data is not None:
                    np.savez_compressed(target, **data)


def cmd_court(args: argparse.Namespace) -> None:
    pts = courts(args.out)
    debug = args.out / "debug"
    debug.mkdir(exist_ok=True)
    detector, posenet = PersonDetector(size=args.size), RTMPose()
    for video_id in args.video_ids:
        labels = read_labels(args.labels, video_id)
        with VideoReader(args.videos / f"{video_id}.mp4") as video:
            t = labels.games[0].rallies[0].start_t - 0.4
            frame = video[int(np.searchsorted(video.times, t))]
        image = frame.image
        h, w = image.shape[:2]
        floor, rms = fit_floor(pts[video_id], w, h)
        canvas = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        for line in court_lines():
            cv2.polylines(canvas, [floor.to_image(line).astype(np.int32)], False, (0, 255, 255), 2)
        det = detector(image)
        kps = posenet(image, det.boxes)
        for box, k, c in zip(det.boxes, kps, det.conf, strict=True):
            fp = foot_point(box, k, float(c), h)
            x1, y1, x2, y2 = box.astype(int)
            court = fp is not None and on_court(*floor.to_court(np.array([[fp.x, fp.y]]))[0])
            cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 200, 0) if court else (0, 0, 200), 2)
            for x, y, s in k:
                if s >= 0.3:
                    cv2.circle(canvas, (int(x), int(y)), 3, (255, 0, 255), -1)
            if fp is not None:
                colour = (0, 0, 255) if fp.estimated else (255, 255, 0)
                cv2.drawMarker(canvas, (int(fp.x), int(min(fp.y, h - 3))), colour, 0, 18, 3)
        cv2.imwrite(str(debug / f"{video_id}_court.jpg"), canvas)
        print(f"{video_id}: RMS {rms:.2f} ft, k1 {floor.k1:.3f}, {len(det.boxes)} people")


# Score ---------------------------------------------------------------------------------------


@dataclass
class View:
    """The serving team's two people at one serve, as rows of the game's data per frame."""

    server: list[int]
    partner: list[int]
    others: list[tuple[int, int]]
    """The other half's two people per frame: first the one on the serve's side, where the
    receiver stands, then the other."""


def window_rows(data: dict[str, np.ndarray], t: float) -> dict[int, list[int]]:
    lo, hi = t + WINDOW[0], t + WINDOW[1]
    rows = np.flatnonzero((data["t"] >= lo) & (data["t"] <= hi))
    by_frame: dict[int, list[int]] = defaultdict(list)
    for r in rows:
        by_frame[int(data["frame"][r])].append(int(r))
    return by_frame


def halves(data: dict[str, np.ndarray], rows: list[int]) -> dict[Half, list[int]]:
    """One frame's people by half, at most the two nearest the lines in each."""
    out: dict[Half, list[int]] = {}
    for half in ("near", "far"):
        mine = [r for r in rows if zones.half(tuple(data["foot_ft"][r])) == half]
        keep = nearest_two([tuple(data["foot_ft"][r]) for r in mine])
        out[half] = [mine[i] for i in keep]
    return out


def formation(data: dict[str, np.ndarray], t: float) -> Half | None:
    votes: Counter[Half] = Counter()
    for rows in window_rows(data, t).values():
        by_half = halves(data, rows)
        vote = serving_half(
            [tuple(data["foot_ft"][r]) for r in by_half["near"]],
            [tuple(data["foot_ft"][r]) for r in by_half["far"]],
        )
        if vote is not None:
            votes[vote] += 1
    return votes.most_common(1)[0][0] if votes else None


def serve_view(data: dict[str, np.ndarray], t: float, half: Half, side: str) -> View:
    view = View([], [], [])
    other = zones.other_half(half)
    for rows in window_rows(data, t).values():
        by_half = halves(data, rows)
        mine, theirs = by_half[half], by_half[other]
        if len(mine) == 2:
            s, p = split_server([data["foot_ft"][r][0] for r in mine], half, side)
            view.server.append(mine[s])
            view.partner.append(mine[p])
        if len(theirs) == 2:
            on_side, off_side = split_server([data["foot_ft"][r][0] for r in theirs], other, side)
            view.others.append((theirs[on_side], theirs[off_side]))
    return view


def mean_of(data: dict[str, np.ndarray], key: str, rows: list[int]) -> np.ndarray:
    v = data[key][rows].astype(np.float64).mean(axis=0)
    return v / np.linalg.norm(v)


def main_track(data: dict[str, np.ndarray], rows: list[int]) -> int:
    tracks = [int(data["track"][r]) for r in rows if data["track"][r] >= 0]
    return Counter(tracks).most_common(1)[0][0] if tracks else -1


def track_mean(data: dict[str, np.ndarray], key: str, track: int, until: float) -> np.ndarray:
    rows = np.flatnonzero((data["track"] == track) & (data["t"] <= until))
    return mean_of(data, key, rows.tolist())


S = TypeVar("S")


def sighting(view: View, see: Callable[[list[int]], S]) -> Sighting[S]:
    """What one method sees at a serve, from the rows of each person across the window."""
    receivers = [r for r, _ in view.others], [r for _, r in view.others]
    return Sighting(
        see(view.server) if view.server else None,
        see(view.partner) if view.partner else None,
        see(receivers[0]) if view.others else None,
        see(receivers[1]) if view.others else None,
    )


@dataclass
class TrackMethod:
    """ByteTrack ids alone. A person whose track wasn't enrolled is named from their partner's
    track if that one was. An untracked person is track -1."""

    name: str = "track"
    track_of: dict[int, PlayerId] = field(default_factory=dict)

    def enrol(self, player: PlayerId, seen: int) -> None:
        if seen >= 0:
            self.track_of[seen] = player

    def name_server(
        self, pair: tuple[PlayerId, PlayerId], server: int, partner: int
    ) -> tuple[PlayerId | None, float]:
        if server in self.track_of:
            return self.track_of[server], 0.0
        if partner in self.track_of:
            return PARTNER[self.track_of[partner]], 0.0
        return None, 0.0


def score_game(
    video_id: str, game: LabelGame, data: dict[str, np.ndarray], first_of_recording: bool
) -> list[ServeResult]:
    serves = sorted(game.rallies, key=lambda r: r.start_t)
    votes: list[tuple[str, Half]] = []
    for rally in serves:
        vote = formation(data, rally.start_t)
        if vote is not None:
            votes.append((team_of(rally.serve.server), vote))
    a_half, agree = team_a_half(votes)
    if a_half is None:
        print(f"{video_id} {game.id}: no formation votes", file=sys.stderr)
        return []
    print(f"{video_id} {game.id}: team A {a_half}, {agree:.0%} of formation votes agree")

    gold: list[GoldServe] = []
    seen: dict[str, list[Sighting[Any]]] = defaultdict(list)
    side_checks = []
    for rally in serves:
        team = team_of(rally.serve.server)
        half = a_half if team == "A" else zones.other_half(a_half)
        view = serve_view(data, rally.start_t, half, rally.serve.side)
        if view.others:  # the receiver stands deeper than their partner at the kitchen
            on_side, off_side = view.others[-1]
            gap = [abs(data["foot_ft"][r][1] - zones.NET_Y) for r in (on_side, off_side)]
            side_checks.append(gap[0] > gap[1])
        gold.append(GoldServe(rally.id, rally.start_t, rally.serve.server, half))
        until = rally.start_t + WINDOW[1]

        def tracked_dino(rows: list[int], until: float = until) -> np.ndarray:
            track = main_track(data, rows)
            if track < 0:
                return mean_of(data, "dino", rows)
            return track_mean(data, "dino", track, until)

        for key in ("colour", "dino"):
            look = sighting(view, lambda rows, key=key: mean_of(data, key, rows))
            seen[key].append(look)
            seen[f"{key} online"].append(look)
        seen["track"].append(sighting(view, lambda rows: main_track(data, rows)))
        seen["track + dino"].append(sighting(view, tracked_dino))

    methods = [
        ProfileMethod("colour"),
        ProfileMethod("colour online", online=True),
        ProfileMethod("dino"),
        ProfileMethod("dino online", online=True),
        TrackMethod(),
        ProfileMethod("track + dino"),
    ]
    results: list[ServeResult] = []
    for method in methods:
        results += check_game(
            video_id, gold, seen[method.name], method, first_of_recording=first_of_recording
        )
    if side_checks:
        share = np.mean(side_checks)
        print(f"  receiver on the gold side at {share:.0%} of {len(side_checks)} serves")
    return results


def cmd_score(args: argparse.Namespace) -> None:
    results: list[ServeResult] = []
    for path in sorted(args.out.glob("v_*_g*.npz")):
        video_id, game_id = path.stem.rsplit("_", 1)
        labels = read_labels(args.labels, video_id)
        game = next(g for g in labels.games if g.id == game_id)
        first = min(labels.games, key=lambda g: g.start_t)
        with np.load(path) as npz:
            data = {k: npz[k] for k in npz.files}
        if "t" not in data:
            print(f"{path.name} has no players, skipped", file=sys.stderr)
            continue
        results += score_game(video_id, game, data, first_of_recording=game.id == first.id)
        near = data["foot_ft"][:, 1] > zones.NET_Y
        if near.any():
            hips = data["source"][near] == SOURCES["hips"]
            print(f"  near-half foot points from the hips: {hips.mean():.0%}")
    with (args.out / "results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(ServeResult.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(r) for r in results)
    print("\n| Method | Team | Serves | Server found | Correct | Accuracy | 95% interval |")
    print("|---|---|---|---|---|---|---|")
    for row in summarise(results):
        lo, hi = row.interval
        print(
            f"| {row.method} | {row.half} | {row.serves} | {row.found} | {row.correct} "
            f"| {row.accuracy:.0%} | {lo:.0%} to {hi:.0%} |"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="The M0 player spike (#47).")
    parser.add_argument("command", choices=["court", "extract", "score"])
    parser.add_argument("video_ids", nargs="*")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--videos", type=Path, default=Path("data/videos"))
    parser.add_argument("--labels", type=Path, default=Path("labels/gold-rallies"))
    parser.add_argument("--size", default="medium", choices=["nano", "small", "medium", "large"])
    args = parser.parse_args()
    {"court": cmd_court, "extract": cmd_extract, "score": cmd_score}[args.command](args)


if __name__ == "__main__":
    main()
