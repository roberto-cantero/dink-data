"""The studio's files in R2: the video it opens, and the label folders it reads and writes.

Labels are saved locally first and then uploaded, so a save never waits on the network and
never fails because of it (docs/DATA.md). Uploads use `--immutable`, and versions are never
replaced, so anything not yet in R2 is uploaded at the next save or start. Before a save, the
folder is pulled from R2, so a new version numbers after any saved on another machine.

R2 keys mirror the local folder: `labels/gold-events/<video_id>/<handle>/v<n>.json` is
`<labels>/gold-events/<video_id>/<handle>/v<n>.json` on disk.
"""

from pathlib import Path

from dinkdata.data.r2 import ListingStore, RcloneStore, Store

LabelStore = ListingStore
"""R2 with the folder listing the studio needs."""
RcloneLabelStore = RcloneStore
"""The R2 bucket. Its folder listing moved to `RcloneStore` for the versioned save."""


def pull(store: LabelStore, labels: Path, folder: str) -> list[str]:
    """Download the files in `labels/<folder>` that R2 has and this machine doesn't."""
    fetched = []
    for name in store.files(f"labels/{folder}"):
        local = labels / folder / name
        if not local.exists():
            _download(store, f"labels/{folder}/{name}", local)
            fetched.append(name)
    return fetched


def push(store: LabelStore, labels: Path, folder: str) -> list[str]:
    """Upload the files in `labels/<folder>` that R2 doesn't have yet, oldest first."""
    remote = set(store.files(f"labels/{folder}"))
    uploaded = []
    for name in _local(labels / folder):
        if name not in remote:
            store.put(labels / folder / name, f"labels/{folder}/{name}")
            uploaded.append(name)
    return uploaded


def pending(store: LabelStore, labels: Path, folder: str) -> int:
    """How many local files in `labels/<folder>` aren't in R2 yet."""
    remote = set(store.files(f"labels/{folder}"))
    return sum(name not in remote for name in _local(labels / folder))


def handles(store: LabelStore | None, labels: Path, kind: str, video_id: str) -> list[str]:
    """The labellers with a `kind` folder (such as gold-rallies) for the video, here or in R2."""
    found = set()
    base = labels / kind / video_id
    if base.is_dir():
        found.update(p.name for p in base.iterdir() if p.is_dir())
    if store is not None:
        found.update(name.split("/")[0] for name in store.files(f"labels/{kind}/{video_id}"))
    return sorted(found)


def fetch_video(store: Store | None, videos: Path, video_id: str) -> tuple[Path, Path]:
    """The video and its frames.parquet in `videos`, downloaded from R2 if missing."""
    paths = (videos / f"{video_id}.mp4", videos / f"{video_id}.frames.parquet")
    for path in paths:
        if path.is_file():
            continue
        if store is None:
            raise ValueError(
                f"no {path.name} in {videos}. Save it there, or start the studio with R2 "
                "(uv run --env-file .env) to download it."
            )
        _download(store, f"videos/{path.name}", path)
    return paths


def _download(store: Store, key: str, local: Path) -> None:
    """Download through a temporary name, so a broken download leaves no partial file."""
    local.parent.mkdir(parents=True, exist_ok=True)
    part = local.with_name(f".{local.name}.part")
    try:
        store.get(key, part)
        part.rename(local)
    finally:
        part.unlink(missing_ok=True)


def _local(folder: Path) -> list[str]:
    if not folder.is_dir():
        return []
    names = (str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())
    return sorted(n for n in names if not any(part.startswith(".") for part in Path(n).parts))
