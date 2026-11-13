"""A local folder that stands in for the R2 bucket in tests."""

import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path


class FolderStore:
    """Files under `root`, with the same paths as in R2. Records every upload.

    `before_write`, when set, runs with the path just before any write that replaces a file.
    A test uses it to run a second ingest between the first one's read and its write.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.puts: list[str] = []
        self.before_write: Callable[[str], None] | None = None

    def exists(self, path: str) -> bool:
        return (self.root / path).is_file()

    def get(self, path: str, local: Path) -> None:
        shutil.copyfile(self.root / path, local)

    def put(self, local: Path, path: str, overwrite: bool = False) -> None:
        target = self.root / path
        if overwrite and self.before_write is not None:
            self.before_write(path)
        if target.exists() and not overwrite:
            raise FileExistsError(path)
        self._write(local, path)

    def get_versioned(self, path: str, local: Path) -> str | None:
        if not self.exists(path):
            return None
        self.get(path, local)
        return self._etag(path)

    def put_if(self, local: Path, path: str, etag: str | None) -> bool:
        if self.before_write is not None:
            self.before_write(path)
        current = self._etag(path) if self.exists(path) else None
        if current != etag:
            return False
        self._write(local, path)
        return True

    def _etag(self, path: str) -> str:
        return hashlib.md5((self.root / path).read_bytes()).hexdigest()

    def _write(self, local: Path, path: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local, target)
        self.puts.append(path)
