"""Partner identity at the serve, measured against hand-labelled serves (DESIGN 6.6 step 6, 10).

The check stands in for a perfect serve-state detector, which is M2 work: the gold label says
which team serves and from which side, and the court positions say where that team stands. The
serving team's player on the gold side is the server. An identity method then has to say which
of the team's two players that person is, and the check compares its answer with the gold
server. Results are split by the half the serving team stands in, near or far.

Court coordinates follow docs/COURT.md and `dinkdata.court.zones`. The near team faces away
from the camera, so its right is larger x. The far team faces the camera, so its right is
smaller x.
"""

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

import numpy as np

from dinkdata.contracts.common import PlayerId, team_of
from dinkdata.court.zones import CENTRE_X, LENGTH, NET_Y, WIDTH, Half, other_half
from dinkdata.players.identity import Profile, assign_pair

SIDE_MARGIN = 4.0
BACK_MARGIN = 16.0
"""Feet outside the sidelines and behind the baselines that still count as our court."""

PARTNER: dict[PlayerId, PlayerId] = {"p1": "p2", "p2": "p1", "p3": "p4", "p4": "p3"}
PAIRS: dict[str, tuple[PlayerId, PlayerId]] = {"A": ("p1", "p2"), "B": ("p3", "p4")}


def on_court(x: float, y: float) -> bool:
    """Whether a foot point in feet is on our court, with margins for play outside the lines."""
    return -SIDE_MARGIN <= x <= WIDTH + SIDE_MARGIN and -BACK_MARGIN <= y <= LENGTH + BACK_MARGIN


def nearest_two(points: Sequence[tuple[float, float]]) -> list[int]:
    """Indices of the two points closest to the court lines, in their original order. Players
    stand inside or just outside the lines, spectators and waiting players further out."""

    def outside(p: tuple[float, float]) -> float:
        x, y = p
        return max(-x, x - WIDTH, 0.0) + max(-y, y - LENGTH, 0.0)

    return sorted(sorted(range(len(points)), key=lambda i: outside(points[i]))[:2])


def split_server(xs: Sequence[float], half: Half, side: str) -> tuple[int, int]:
    """Which of a team's two people serves from `side` ("left" or "right", from the players'
    own view), as (server index, partner index)."""
    rightness = [x - CENTRE_X if half == "near" else CENTRE_X - x for x in xs]
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


def team_a_half(votes: Iterable[tuple[str, Half]]) -> tuple[Half | None, float]:
    """Team A's half in a game from (gold serving team, formation's serving half) votes, and the
    share of votes that agree with it."""
    counts: Counter[Half] = Counter()
    for team, serving in votes:
        counts[serving if team == "A" else other_half(serving)] += 1
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


# One game's serves -------------------------------------------------------------------------

S = TypeVar("S")
S_in = TypeVar("S_in", contravariant=True)


@dataclass(frozen=True)
class GoldServe:
    rally_id: str
    t: float
    server: PlayerId
    half: Half
    """The serving team's half."""


@dataclass(frozen=True)
class Sighting(Generic[S]):
    """What one method sees of the players at one serve, such as a feature vector or a track id.
    None where the person wasn't found."""

    server: S | None = None
    partner: S | None = None
    receiver: S | None = None
    """The receiving team's player on the serve's side, who receives it."""
    receiver_partner: S | None = None


class Method(Protocol[S_in]):
    name: str

    def enrol(self, player: PlayerId, seen: S_in) -> None: ...

    def name_server(
        self, pair: tuple[PlayerId, PlayerId], server: S_in, partner: S_in
    ) -> tuple[PlayerId | None, float]:
        """Which of `pair` the server is, or None, and the margin of the answer."""
        ...


@dataclass
class ProfileMethod:
    """Appearance profiles from each player's enrolment. With `online`, every answer also adds
    the two people's features to the profiles it named them as, without looking at gold."""

    name: str
    online: bool = False
    profiles: dict[PlayerId, Profile] = field(default_factory=dict)

    def enrol(self, player: PlayerId, seen: np.ndarray) -> None:
        self.profiles[player] = Profile.of([seen])

    def name_server(
        self, pair: tuple[PlayerId, PlayerId], server: np.ndarray, partner: np.ndarray
    ) -> tuple[PlayerId | None, float]:
        order, margin = assign_pair(
            np.stack([server, partner]), [self.profiles[p].vector for p in pair]
        )
        named = pair[order[0]]
        if self.online:
            self.profiles[named].add(server)
            self.profiles[PARTNER[named]].add(partner)
        return named, margin


def check_game(
    video_id: str,
    serves: Sequence[GoldServe],
    sightings: Sequence[Sighting[S]],
    method: Method[S],
    *,
    first_of_recording: bool,
) -> list[ServeResult]:
    """Partner identity at each serve of one game, in time order.

    A team enrols at its first serve where both its people are seen: the gold server and their
    partner. Only the recording's first serve also enrols the receiving team, because p3 is
    defined as the recording's first receiver (GLOSSARY), not each game's. A serve that enrols
    its team isn't scored. A scored serve with either person unseen names nobody.
    """
    enrolled: set[PlayerId] = set()
    results: list[ServeResult] = []
    for n, (serve, seen) in enumerate(zip(serves, sightings, strict=True)):
        pair = PAIRS[team_of(serve.server)]
        receiver, receiver_partner = seen.receiver, seen.receiver_partner
        if n == 0 and first_of_recording and receiver is not None and receiver_partner is not None:
            receivers = PAIRS["B" if team_of(serve.server) == "A" else "A"]
            method.enrol(receivers[0], receiver)
            method.enrol(receivers[1], receiver_partner)
            enrolled.update(receivers)
        if not set(pair) <= enrolled:
            if seen.server is not None and seen.partner is not None:
                method.enrol(serve.server, seen.server)
                method.enrol(PARTNER[serve.server], seen.partner)
                enrolled.update(pair)
            continue
        if seen.server is None or seen.partner is None:
            named, margin = None, 0.0
        else:
            named, margin = method.name_server(pair, seen.server, seen.partner)
        results.append(
            ServeResult(
                video_id,
                serve.rally_id,
                serve.t,
                serve.half,
                method.name,
                serve.server,
                named,
                margin,
            )
        )
    return results


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
