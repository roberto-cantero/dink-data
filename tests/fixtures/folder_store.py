"""A local folder that stands in for the R2 bucket in tests."""

import shutil
from pathlib import Path


class FolderStore:
    """Files under `root`, with the same paths as in R2. Records every upload."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.puts: list[str] = []

    def exists(self, path: str) -> bool:
        return (self.root / path).is_file()

    def get(self, path: str, local: Path) -> None:
        shutil.copyfile(self.root / path, local)

    def put(self, local: Path, path: str, overwrite: bool = False) -> None:
        target = self.root / path
        if target.exists() and not overwrite:
            raise FileExistsError(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local, target)
        self.puts.append(path)
