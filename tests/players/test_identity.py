"""Partner identity: two people of a team matched to the team's two stored profiles."""

import numpy as np
import pytest

from dinkdata.players.identity import Profile, assign_pair


def unit(*values: float) -> np.ndarray:
    v = np.array(values, dtype=np.float64)
    return v / np.linalg.norm(v)


def test_a_profile_is_the_normalised_mean_of_its_features():
    profile = Profile.of([unit(1, 0), unit(0, 1)])
    assert profile.n == 2
    assert profile.vector == pytest.approx(unit(1, 1))
    profile.add(unit(1, 0))
    assert profile.n == 3
    assert profile.vector == pytest.approx(unit(2, 1))


def test_people_in_profile_order_keep_their_order():
    order, margin = assign_pair(np.stack([unit(1, 0.1), unit(0.1, 1)]), [unit(1, 0), unit(0, 1)])
    assert order == (0, 1)
    assert margin > 0.5


def test_swapped_people_are_swapped():
    order, _ = assign_pair(np.stack([unit(0.1, 1), unit(1, 0.1)]), [unit(1, 0), unit(0, 1)])
    assert order == (1, 0)


def test_the_pair_decides_even_when_both_look_like_one_profile():
    """Both people resemble profile 0, but the first resembles it more, so it takes it."""
    order, margin = assign_pair(np.stack([unit(1, 0.2), unit(1, 0.6)]), [unit(1, 0), unit(0, 1)])
    assert order == (0, 1)
    assert 0 < margin < 0.5


def test_identical_profiles_give_no_margin():
    _, margin = assign_pair(np.stack([unit(1, 0), unit(0, 1)]), [unit(1, 1), unit(1, 1)])
    assert margin == pytest.approx(0)
