"""Partner identity at the serve, measured against hand-labelled serves (DESIGN 6.6 step 6, 10).

The check stands in for a perfect serve-state detector, which is M2 work: the gold label says
which team serves and from which side, and the court positions say where that team stands. The
serving team's player on the gold side is the server. An identity method then has to say which
of the team's two players that person is, and the check compares its answer with the gold
server. Results are split by the half the serving team stands in, near or far.

Court coordinates follow docs/COURT.md: x runs 0 to 20 across the court as the camera sees it,
y runs 0 to 44 toward the camera, and the net is at y = 22. The near team faces away from the
camera, so its right is larger x. The far team faces the camera, so its right is smaller x.
"""

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

Half = Literal["near", "far"]

NET_Y = 22.0
COURT_W, COURT_L = 20.0, 44.0
SIDE_MARGIN = 4.0
BACK_MARGIN = 16.0
"""Feet outside the sidelines and behind the baselines that still count as our court."""


def on_court(x: float, y: float) -> bool:
    """Whether a foot point in feet is on our court, with margins for play outside the lines."""
    return -SIDE_MARGIN <= x <= COURT_W + SIDE_MARGIN and -BACK_MARGIN <= y <= COURT_L + BACK_MARGIN


def nearest_two(points: Sequence[tuple[float, float]]) -> list[int]:
    """Indices of the two points closest to the court lines, in their original order. Players
    stand inside or just outside the lines, spectators and waiting players further out."""

    def outside(p: tuple[float, float]) -> float:
        x, y = p
        return max(-x, x - COURT_W, 0.0) + max(-y, y - COURT_L, 0.0)

    return sorted(sorted(range(len(points)), key=lambda i: outside(points[i]))[:2])


def half_of(y: float) -> Half:
    return "near" if y > NET_Y else "far"


def split_server(xs: Sequence[float], half: Half, side: str) -> tuple[int, int]:
    """Which of a team's two people serves from `side` ("left" or "right", from the players'
    own view), as (server index, partner index)."""
    rightness = [x - COURT_W / 2 if half == "near" else COURT_W / 2 - x for x in xs]
    right = 0 if rightness[0] >= rightness[1] else 1
    server = right if side == "right" else 1 - right
    return server, 1 - server


def serving_half(
    near: Sequence[tuple[float, float]], far: Sequence[tuple[float, float]]
) -> Half | None:
    """The half whose team serves, from the formation: the receiver's partner waits at the
    kitchen, so the receiving half has someone closer to the net. None without both halves."""
    if not near or not far:
        return None
    near_gap = min(y - NET_Y for _, y in near)
    far_gap = min(NET_Y - y for _, y in far)
    return "near" if near_gap > far_gap else "far"


def team_a_half(votes: Iterable[tuple[str, str]]) -> tuple[Half | None, float]:
    """Team A's half in a game from (gold serving team, formation's serving half) votes, and the
    share of votes that agree with it."""
    counts: Counter[Half] = Counter()
    for team, serving in votes:
        mine: Half = "near" if serving == "near" else "far"
        other: Half = "far" if mine == "near" else "near"
        counts[mine if team == "A" else other] += 1
    if not counts:
        return None, 0.0
    half, n = counts.most_common(1)[0]
    return half, n / sum(counts.values())


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """The Wilson score interval of k successes in n, 95% by default."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - spread, centre + spread


@dataclass(frozen=True)
class ServeResult:
    video_id: str
    rally_id: str
    t: float
    half: Half
    """The serving team's half."""
    method: str
    gold: str
    predicted: str | None
    """None when the method couldn't name the server, for example with no server box."""
    margin: float


@dataclass(frozen=True)
class SummaryRow:
    method: str
    half: str
    serves: int
    found: int
    correct: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.found if self.found else 0.0

    @property
    def interval(self) -> tuple[float, float]:
        return wilson(self.correct, self.found)


def summarise(results: Iterable[ServeResult]) -> list[SummaryRow]:
    """Accuracy among the serves where the method named someone, per method and half, plus
    both halves together."""
    rows: list[SummaryRow] = []
    results = list(results)
    for method in dict.fromkeys(r.method for r in results):
        mine = [r for r in results if r.method == method]
        for half in ("near", "far", "both"):
            part = [r for r in mine if half == "both" or r.half == half]
            found = [r for r in part if r.predicted is not None]
            correct = sum(r.predicted == r.gold for r in found)
            rows.append(SummaryRow(method, half, len(part), len(found), correct))
    return rows
