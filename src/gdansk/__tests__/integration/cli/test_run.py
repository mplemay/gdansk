from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gdansk.__tests__.conftest import run_cli, write_pyproject

pytestmark = pytest.mark.integration


def test_run_package_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_pyproject(
        tmp_path,
        dependencies={"semver": "7.7.2"},
        commands={"semver-help": ["semver", "--help"]},
    )

    code, _stdout, _stderr = run_cli(["lock"], monkeypatch=monkeypatch, cwd=tmp_path, capsys=capsys)
    assert code == 0
    code, _stdout, _stderr = run_cli(
        ["run", "semver-help"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )
    assert code == 0


def test_run_watch_stops_on_signal(tmp_path: Path):
    is_windows = sys.platform == "win32"
    write_pyproject(
        tmp_path,
        dependencies={"zx": "8.5.5"},
        commands={"idle": ["zx", "idle.mjs"]},
    )
    (tmp_path / "idle.mjs").write_text(
        'import fs from "node:fs";\nfs.writeFileSync("watch-ready", "");\nsetInterval(() => {}, 1000);\n',
        encoding="utf-8",
    )
    subprocess.run(
        [sys.executable, "-m", "gdansk", "lock"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    command = [sys.executable, "-m", "gdansk", "run", "idle", "--watch"]
    if is_windows:
        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=tmp_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=tmp_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    try:
        ready = tmp_path / "watch-ready"
        deadline = time.monotonic() + 60
        while not ready.is_file():
            if (returncode := process.poll()) is not None:
                pytest.fail(f"process exited early with {returncode}")
            if time.monotonic() > deadline:
                pytest.fail("timed out waiting for watch-ready")
            time.sleep(0.1)
        stop_signal = signal.CTRL_BREAK_EVENT if is_windows else signal.SIGINT
        process.send_signal(stop_signal)
        stdout, stderr = process.communicate(timeout=30)
        if is_windows:
            assert process.returncode == 0, (stdout, stderr)
        else:
            assert process.returncode in {0, -2, -15}, (stdout, stderr)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)
