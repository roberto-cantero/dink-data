"""Synthetic cameras for the floor function tests. No real footage.

Court coordinates are right-handed, so with x across the court and y toward the camera, z
points down into the floor. A camera `height` ft above the floor sits at z = -height.
"""

from typing import Any, TypedDict

import numpy as np

from dinkdata.contracts.camera import CameraCalibration

CAMERA_ID = "c_5eed00000000c0de"
WIDTH, HEIGHT = 1920, 1080


def calibration(
    rotation: tuple[float, float, float],
    translation: tuple[float, float, float],
    *,
    f: float = 1000.0,
    k1: float = 0.0,
    k2: float = 0.0,
    setup: str = "dtl_low",
    version: int = 1,
) -> CameraCalibration:
    return CameraCalibration.model_validate(
        camera_json(rotation, translation, f, k1, k2, setup, version)
    )


def camera_json(
    rotation: tuple[float, float, float],
    translation: tuple[float, float, float],
    f: float = 1000.0,
    k1: float = 0.0,
    k2: float = 0.0,
    setup: str = "dtl_low",
    version: int = 1,
) -> dict[str, Any]:
    return {
        "schema": "dinkdata.camera/v1",
        "camera_id": CAMERA_ID,
        "version": version,
        "model": None,
        "setup": setup,
        "image_size": {"width": WIDTH, "height": HEIGHT},
        "intrinsics": {"fx": f, "fy": f, "cx": WIDTH / 2, "cy": HEIGHT / 2},
        "distortion": {"k1": k1, "k2": k2},
        "rotation": list(rotation),
        "translation": list(translation),
        "reprojection_error_px": 1.0,
        "visible_region": [[0.0, 0.0], [20.0, 0.0], [20.0, 44.0], [0.0, 44.0]],
        "overlay_masks": [],
        "source": "clicks",
    }


def looking_at(
    x: float,
    y: float,
    height: float,
    target: tuple[float, float],
    *,
    f: float = 1000.0,
    k1: float = 0.0,
    k2: float = 0.0,
    setup: str = "dtl_low",
) -> CameraCalibration:
    """A camera at (x, y) and `height` ft up, aimed at a floor point, with no roll."""
    centre = np.array([x, y, -height])
    forward = np.array([target[0], target[1], 0.0]) - centre
    forward /= np.linalg.norm(forward)
    down = np.array([0.0, 0.0, 1.0])
    right = np.cross(down, forward)
    right /= np.linalg.norm(right)
    rot = np.stack([right, np.cross(forward, right), forward])
    t = -rot @ centre
    return calibration(_rotation_vector(rot), (t[0], t[1], t[2]), f=f, k1=k1, k2=k2, setup=setup)


def _rotation_vector(rot: np.ndarray) -> tuple[float, float, float]:
    angle = float(np.arccos(np.clip((np.trace(rot) - 1) / 2, -1, 1)))
    axis = np.array([rot[2, 1] - rot[1, 2], rot[0, 2] - rot[2, 0], rot[1, 0] - rot[0, 1]])
    vec = axis / (2 * np.sin(angle)) * angle
    return (float(vec[0]), float(vec[1]), float(vec[2]))


BARREL: dict[str, float] = {"k1": -0.25, "k2": 0.06}
"""A wide-angle lens that bends lines outward and stays monotonic across the image."""


class Setup(TypedDict):
    x: float
    y: float
    height: float
    target: tuple[float, float]
    setup: str


SETUPS: dict[str, Setup] = {
    "dtl_low": Setup(x=10.0, y=54.0, height=5.0, target=(10.0, 20.0), setup="dtl_low"),
    "dtl_high": Setup(x=10.0, y=56.0, height=15.0, target=(10.0, 20.0), setup="dtl_high"),
    "diagonal": Setup(x=26.0, y=52.0, height=10.0, target=(10.0, 22.0), setup="diagonal"),
}
