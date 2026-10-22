"""The pod start script: the stop timer and the command it runs (docs/OPERATIONS.md)."""

import os
import subprocess
import time
from pathlib import Path

import pytest

START = Path(__file__).parents[2] / "docker" / "start.sh"


@pytest.fixture
def fake_runpodctl(tmp_path: Path) -> tuple[Path, Path]:
    """A runpodctl that records its arguments instead of calling RunPod."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "runpodctl.log"
    script = bin_dir / "runpodctl"
    script.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{log}"\n')
    script.chmod(0o755)
    return bin_dir, log


def run_start(bin_dir: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if k not in ("RUNPOD_POD_ID", "PUBLIC_KEY")}
    clean["PATH"] = f"{bin_dir}{os.pathsep}{clean['PATH']}"
    return subprocess.run(
        ["bash", str(START), *args],
        env=clean | env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def wait_for(path: Path, seconds: float = 5) -> str:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and path.read_text():
            return path.read_text()
        time.sleep(0.1)
    return path.read_text() if path.exists() else ""


def test_stops_the_pod_after_the_timer(fake_runpodctl: tuple[Path, Path]) -> None:
    bin_dir, log = fake_runpodctl
    result = run_start(bin_dir, "true", RUNPOD_POD_ID="pod123", DINK_STOP_AFTER_S="1")
    assert result.returncode == 0, result.stderr
    assert wait_for(log) == "pod stop pod123\n"


def test_runs_the_command_it_is_given(fake_runpodctl: tuple[Path, Path], tmp_path: Path) -> None:
    bin_dir, _ = fake_runpodctl
    marker = tmp_path / "ran"
    result = run_start(bin_dir, "touch", str(marker), DINK_STOP_AFTER_S="60")
    assert result.returncode == 0, result.stderr
    assert marker.exists()


def test_no_timer_outside_a_pod(fake_runpodctl: tuple[Path, Path]) -> None:
    bin_dir, log = fake_runpodctl
    result = run_start(bin_dir, "true", DINK_STOP_AFTER_S="1")
    assert result.returncode == 0, result.stderr
    time.sleep(2)
    assert not log.exists()
    assert "no stop timer" in result.stderr


def test_rejects_a_timer_that_isnt_whole_seconds(fake_runpodctl: tuple[Path, Path]) -> None:
    bin_dir, log = fake_runpodctl
    result = run_start(bin_dir, "true", RUNPOD_POD_ID="pod123", DINK_STOP_AFTER_S="4h")
    assert result.returncode != 0
    assert "DINK_STOP_AFTER_S" in result.stderr
    assert not log.exists()


def test_dockerignore_keeps_secrets_and_data_out() -> None:
    ignored = (Path(__file__).parents[2] / ".dockerignore").read_text().split()
    for entry in (".env", ".env.*", "data/", "labels/", "runs/", "ckpts/", "out/", ".venv/"):
        assert entry in ignored, f".dockerignore must list {entry}"
