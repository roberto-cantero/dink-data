"""Versioned label files: every save is a new `v<n>` file, and nothing is overwritten.

Labels live under a local `labels/` folder, which git ignores, until the R2 store exists
(docs/DATA.md). The layout matches R2's: `labels/gold-rallies/<video_id>/<labeller>/v<n>.json`,
with the player reference crops beside it in `crops/<player>/v<n>.png`.
"""

import re
from pathlib import Path

from dinkdata.contracts.common import PlayerId

GOLD_RALLIES = "gold-rallies"

_VERSION = re.compile(r"v([1-9][0-9]*)")
_CROP_FOLDERS: dict[str, str] = {"p1": "p1", "p2": "p2", "p3": "p3", "p4": "p4"}


def rally_folder(labels: Path, video_id: str, labeller: str) -> Path:
    return labels / GOLD_RALLIES / video_id / labeller


def crop_folder(labels: Path, video_id: str, labeller: str, player: PlayerId) -> Path:
    """The crops folder for one player. `player` often comes from a request, so the folder
    name is looked up in a fixed table instead of being built from it."""
    name = _CROP_FOLDERS.get(player)
    if name is None:
        raise ValueError(f"not a player id: {player!r}")
    return rally_folder(labels, video_id, labeller) / "crops" / name


def versions(folder: Path, suffix: str) -> list[int]:
    """The version numbers saved in `folder`, oldest first."""
    if not folder.is_dir():
        return []
    found = []
    for path in folder.iterdir():
        match = _VERSION.fullmatch(path.stem)
        if path.suffix == suffix and match:
            found.append(int(match.group(1)))
    return sorted(found)


def latest(folder: Path, suffix: str) -> Path | None:
    saved = versions(folder, suffix)
    return folder / f"v{saved[-1]}{suffix}" if saved else None


def write_new_version(folder: Path, data: bytes, suffix: str) -> Path:
    """Write `data` as the next version in `folder`. Never replaces an existing file."""
    folder.mkdir(parents=True, exist_ok=True)
    saved = versions(folder, suffix)
    n = saved[-1] + 1 if saved else 1
    while True:
        path = folder / f"v{n}{suffix}"
        try:
            with path.open("xb") as f:
                f.write(data)
        except FileExistsError:
            n += 1
            continue
        return path
