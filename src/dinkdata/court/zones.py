"""Court zones in feet, from the zone table in docs/COURT.md.

Every function takes a point on the floor, such as a bounce's `court_xy`. Never pass a ball
in the air, because the court mapping is wrong for it (docs/COURT.md). A point is a line's
centre, so a point on a line counts as on it.
"""

from typing import Literal

from dinkdata.contracts.common import Side

Half = Literal["far", "near"]
Point = tuple[float, float]
DepthBucket = Literal["deep", "medium", "short"]

WIDTH = 20.0
LENGTH = 44.0
NET_Y = 22.0
FAR_KITCHEN_Y = 15.0
NEAR_KITCHEN_Y = 29.0
CENTRE_X = 10.0

DEEP_FT = 5.0
"""Deep is this close to the baseline or closer (docs/STATS.md). Provisional."""
MEDIUM_FT = 10.0
"""Medium is over DEEP_FT and up to this far from the baseline. Short is farther. Provisional."""


def half(point: Point) -> Half | None:
    """The half of the court a point is in. None on the net line."""
    y = point[1]
    if y < NET_Y:
        return "far"
    if y > NET_Y:
        return "near"
    return None


def other_half(h: Half) -> Half:
    return "near" if h == "far" else "far"


def in_court(point: Point) -> bool:
    """Inside the sidelines and baselines. The lines are in."""
    x, y = point
    return 0 <= x <= WIDTH and 0 <= y <= LENGTH


def in_service_court(point: Point, server_side: Side) -> bool:
    """Whether a serve bounce is in the service court diagonal from the server.

    The bounce's half is taken as the receivers' half. A server at the near end faces away from
    the camera, so their right is the camera's right and a serve from the right lands left of
    the centre line. A server at the far end faces the camera, so it is the other way round.
    The kitchen line is a fault. The centre line, sideline and baseline are in.
    """
    x, y = point
    h = half(point)
    if h == "far":
        deep_enough = 0 <= y < FAR_KITCHEN_Y
        left_box = server_side == "right"
    elif h == "near":
        deep_enough = NEAR_KITCHEN_Y < y <= LENGTH
        left_box = server_side == "left"
    else:
        return False
    across = 0 <= x <= CENTRE_X if left_box else CENTRE_X <= x <= WIDTH
    return deep_enough and across


def feet_to_baseline(point: Point) -> float:
    """Distance from a point to the baseline of the half it is in."""
    y = point[1]
    return y if y <= NET_Y else LENGTH - y


def depth_bucket(feet: float) -> DepthBucket:
    if feet <= DEEP_FT:
        return "deep"
    if feet <= MEDIUM_FT:
        return "medium"
    return "short"
