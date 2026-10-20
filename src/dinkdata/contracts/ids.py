"""Opaque ids for videos, cameras and facilities (docs/DATA.md, ADR 0016).

An id is a prefix plus the first 16 hex characters of HMAC-SHA256 over PickleCam's own id,
keyed with the secret `DINKDATA_ID_KEY` from `.env`. Nobody without the key can recompute or
reverse an id. `dink catalog sync` and hand-downloaded games use this same function, so a
game labelled before the catalog exists keeps its id.
"""

import hashlib
import hmac
from collections.abc import Mapping
from typing import Literal

ID_KEY_ENV = "DINKDATA_ID_KEY"
MIN_KEY_LENGTH = 16
HEX_CHARS = 16


def make_id(prefix: Literal["v", "c", "f"], raw: str, key: bytes) -> str:
    raw = raw.strip()
    if not raw:
        raise ValueError("raw id is empty")
    digest = hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()
    return f"{prefix}_{digest[:HEX_CHARS]}"


def video_id(session_id: str, key: bytes) -> str:
    return make_id("v", session_id, key)


def camera_id(pickle_cam_camera: str, key: bytes) -> str:
    return make_id("c", pickle_cam_camera, key)


def facility_id(pickle_cam_facility: str, key: bytes) -> str:
    return make_id("f", pickle_cam_facility, key)


def key_from_env(environ: Mapping[str, str]) -> bytes:
    """The HMAC key from the environment. Run with `uv run --env-file .env ...`."""
    key = environ.get(ID_KEY_ENV, "")
    if len(key) < MIN_KEY_LENGTH:
        raise ValueError(
            f"{ID_KEY_ENV} must be set to a secret of at least {MIN_KEY_LENGTH} characters. "
            f"Put it in .env and run with `uv run --env-file .env`."
        )
    return key.encode()
