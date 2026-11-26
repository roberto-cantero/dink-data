"""The named keypoints and court lines from docs/COURT.md, in feet.

Code names them and never numbers them. The coordinates are the court's boundaries, as in
COURT.md. The solver moves the painted lines 1 in to their centres; these names don't.

The names come from `dinkdata.contracts.camera_clicks`, their one definition. This module
keeps only the coordinates.
"""

from dinkdata.contracts.camera_clicks import CourtLine, FloorKeypoint, NetTop
from dinkdata.court.zones import CENTRE_X, FAR_KITCHEN_Y, LENGTH, NEAR_KITCHEN_Y, NET_Y, WIDTH

KeypointName = FloorKeypoint | NetTop

NET_HEIGHT_SIDELINE = 3.0
"""36 in, in feet."""
NET_HEIGHT_CENTRE = 34 / 12
"""34 in, in feet. COURT.md rounds it to 2.83."""

KEYPOINTS: dict[KeypointName, tuple[float, float, float]] = {
    "far_left_corner": (0.0, 0.0, 0.0),
    "far_right_corner": (WIDTH, 0.0, 0.0),
    "near_right_corner": (WIDTH, LENGTH, 0.0),
    "near_left_corner": (0.0, LENGTH, 0.0),
    "far_kitchen_left": (0.0, FAR_KITCHEN_Y, 0.0),
    "far_kitchen_right": (WIDTH, FAR_KITCHEN_Y, 0.0),
    "near_kitchen_right": (WIDTH, NEAR_KITCHEN_Y, 0.0),
    "near_kitchen_left": (0.0, NEAR_KITCHEN_Y, 0.0),
    "far_kitchen_centre": (CENTRE_X, FAR_KITCHEN_Y, 0.0),
    "near_kitchen_centre": (CENTRE_X, NEAR_KITCHEN_Y, 0.0),
    "far_baseline_centre": (CENTRE_X, 0.0, 0.0),
    "near_baseline_centre": (CENTRE_X, LENGTH, 0.0),
    "net_top_left": (0.0, NET_Y, NET_HEIGHT_SIDELINE),
    "net_top_centre": (CENTRE_X, NET_Y, NET_HEIGHT_CENTRE),
    "net_top_right": (WIDTH, NET_Y, NET_HEIGHT_SIDELINE),
}
"""Each keypoint as (x, y, height above the floor) in feet."""

COURT_LINE_ENDS: dict[CourtLine, tuple[tuple[float, float], tuple[float, float]]] = {
    "far_baseline": ((0.0, 0.0), (WIDTH, 0.0)),
    "near_baseline": ((0.0, LENGTH), (WIDTH, LENGTH)),
    "left_sideline": ((0.0, 0.0), (0.0, LENGTH)),
    "right_sideline": ((WIDTH, 0.0), (WIDTH, LENGTH)),
    "far_kitchen_line": ((0.0, FAR_KITCHEN_Y), (WIDTH, FAR_KITCHEN_Y)),
    "near_kitchen_line": ((0.0, NEAR_KITCHEN_Y), (WIDTH, NEAR_KITCHEN_Y)),
    "far_centre_line": ((CENTRE_X, 0.0), (CENTRE_X, FAR_KITCHEN_Y)),
    "near_centre_line": ((CENTRE_X, NEAR_KITCHEN_Y), (CENTRE_X, LENGTH)),
}
"""Each court line's two ends on the floor, in feet. The net's floor line is left out."""
