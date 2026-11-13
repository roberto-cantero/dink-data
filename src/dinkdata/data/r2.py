"""Files in the R2 bucket `dinkdata`, through rclone (docs/DATA.md, "Setting up R2").

The `r2` remote comes from the `RCLONE_CONFIG_R2_*` variables in `.env`, so commands that use
it run with `uv run --env-file .env`. Paths are relative to the bucket, such as
`videos/v_0123456789abcdef.mp4`.

rclone can't send a conditional write, so the shared catalog files go through boto3 with the
same keys. R2 checks `If-Match` and `If-None-Match` in the same step that commits the object,
so of two writers with the same ETag only one succeeds (K3, issue #79).
"""

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# rclone's exit code when a folder doesn't exist. R2 has no real folders, so an empty prefix
# can answer this way.
DIRECTORY_NOT_FOUND = 3
# What S3 answers when a conditional write loses: 412, or 409 when two writes race.
LOST_RACE = {"PreconditionFailed", "ConditionalRequestConflict"}
S3_VARIABLES = (
    "RCLONE_CONFIG_R2_ENDPOINT",
    "RCLONE_CONFIG_R2_ACCESS_KEY_ID",
    "RCLONE_CONFIG_R2_SECRET_ACCESS_KEY",
)


class RcloneError(RuntimeError):
    """An rclone call failed."""


class Store(Protocol):
    def exists(self, path: str) -> bool: ...

    def get(self, path: str, local: Path) -> None: ...

    def put(self, local: Path, path: str, overwrite: bool = False) -> None: ...

    def get_versioned(self, path: str, local: Path) -> str | None:
        """Download a file and return its ETag, or return None if it doesn't exist."""
        ...

    def put_if(self, local: Path, path: str, etag: str | None) -> bool:
        """Upload only if the file still has `etag`, or still doesn't exist when `etag` is None.
        Returns false, and writes nothing, if someone changed it first."""
        ...


def rclone_missing() -> bool:
    return shutil.which("rclone") is None


@dataclass
class RcloneStore:
    remote: str = "r2:dinkdata"
    s3: Any = field(default=None, repr=False, compare=False)
    """A boto3 S3 client, made from the rclone variables on first use. Tests pass a stub."""

    @property
    def bucket(self) -> str:
        return self.remote.partition(":")[2]

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

    def s3_client(self) -> Any:
        if self.s3 is None:
            missing = [name for name in S3_VARIABLES if not os.environ.get(name)]
            if missing:
                raise RcloneError(f"{', '.join(missing)} not set. Run with --env-file .env.")
            import boto3

            self.s3 = boto3.client(
                "s3",
                endpoint_url=os.environ["RCLONE_CONFIG_R2_ENDPOINT"],
                aws_access_key_id=os.environ["RCLONE_CONFIG_R2_ACCESS_KEY_ID"],
                aws_secret_access_key=os.environ["RCLONE_CONFIG_R2_SECRET_ACCESS_KEY"],
                region_name="auto",
            )
        return self.s3

    def get_versioned(self, path: str, local: Path) -> str | None:
        from botocore.exceptions import ClientError

        try:
            answer = self.s3_client().get_object(Bucket=self.bucket, Key=path)
        except ClientError as error:
            if _code(error) == "NoSuchKey":
                return None
            raise RcloneError(f"R2 read of {path} failed: {_code(error)}") from None
        local.write_bytes(answer["Body"].read())
        return answer["ETag"]

    def put_if(self, local: Path, path: str, etag: str | None) -> bool:
        from botocore.exceptions import ClientError

        condition = {"IfMatch": etag} if etag is not None else {"IfNoneMatch": "*"}
        try:
            self.s3_client().put_object(
                Bucket=self.bucket, Key=path, Body=local.read_bytes(), **condition
            )
        except ClientError as error:
            if _code(error) in LOST_RACE:
                return False
            raise RcloneError(f"R2 write of {path} failed: {_code(error)}") from None
        return True


def _code(error: Any) -> str:
    return str(error.response.get("Error", {}).get("Code", "unknown"))
