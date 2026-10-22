"""Partner identity: which of a team's two people is which (GLOSSARY: Partner identity).

Each player has a profile, the normalised mean of their appearance features. At a serve the
team's two people are matched to the team's two profiles as a pair, so the person who looks
more like p1 than their partner does is p1, even if both look a little like p1 (DESIGN 6.6
step 5).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np


def _unit(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


@dataclass
class Profile:
    total: np.ndarray
    n: int

    @classmethod
    def of(cls, features: Iterable[np.ndarray]) -> "Profile":
        stacked = np.stack([_unit(np.asarray(f, dtype=np.float64)) for f in features])
        return cls(total=stacked.sum(axis=0), n=len(stacked))

    def add(self, feature: np.ndarray) -> None:
        self.total = self.total + _unit(np.asarray(feature, dtype=np.float64))
        self.n += 1

    @property
    def vector(self) -> np.ndarray:
        return _unit(self.total)


def assign_pair(
    features: np.ndarray, profiles: Sequence[np.ndarray]
) -> tuple[tuple[int, int], float]:
    """Match two people's features to two profiles.

    Returns the profile index of each person, (0, 1) or (1, 0), and the margin: half the gap in
    summed cosine similarity between the chosen pairing and the other one. 0 means no evidence.
    """
    a, b = (_unit(np.asarray(f, dtype=np.float64)) for f in features)
    p, q = (_unit(np.asarray(v, dtype=np.float64)) for v in profiles)
    kept = float(a @ p + b @ q)
    swapped = float(a @ q + b @ p)
    margin = abs(kept - swapped) / 2
    return ((0, 1) if kept >= swapped else (1, 0)), margin
