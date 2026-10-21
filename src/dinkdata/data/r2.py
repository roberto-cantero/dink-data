"""Files in the R2 bucket `dinkdata`, through rclone (docs/DATA.md, "Setting up R2").

The `r2` remote comes from the `RCLONE_CONFIG_R2_*` variables in `.env`, so commands that use
it run with `uv run --env-file .env`. Paths are relative to the bucket, such as
`videos/v_0123456789abcdef.mp4`.
"""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# rclone's exit code when a folder doesn't exist. R2 has no real folders, so an empty prefix
# can answer this way.
DIRECTORY_NOT_FOUND = 3


class RcloneError(RuntimeError):
    """An rclone call failed."""


class Store(Protocol):
    def exists(self, path: str) -> bool: ...

    def get(self, path: str, local: Path) -> None: ...

    def put(self, local: Path, path: str, overwrite: bool = False) -> None: ...


def rclone_missing() -> bool:
    return shutil.which("rclone") is None


@dataclass(frozen=True)
class RcloneStore:
    remote: str = "r2:dinkdata"

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["rclone", *args], capture_output=True, text=True, check=False)

    def _check(self, result: subprocess.CompletedProcess[str]) -> None:
        if result.returncode != 0:
            raise RcloneError(f"rclone failed: {result.stderr.strip()}")

    def exists(self, path: str) -> bool:
        folder, _, name = path.rpartition("/")
        result = self._run(["lsf", "--files-only", f"{self.remote}/{folder}"])
        if result.returncode == DIRECTORY_NOT_FOUND:
            return False
        self._check(result)
        return name in result.stdout.splitlines()

    def get(self, path: str, local: Path) -> None:
        self._check(self._run(["copyto", f"{self.remote}/{path}", str(local)]))

    def put(self, local: Path, path: str, overwrite: bool = False) -> None:
        """Upload a file. Without `overwrite`, rclone stops if R2 already has a different one."""
        flags = [] if overwrite else ["--immutable"]
        self._check(self._run(["copyto", *flags, str(local), f"{self.remote}/{path}"]))
