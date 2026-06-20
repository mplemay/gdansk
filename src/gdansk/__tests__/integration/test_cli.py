from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gdansk.__tests__.conftest import run_cli, write_pyproject, write_src_layout_project
from gdansk._project import read_pyproject_document

pytestmark = pytest.mark.integration


def test_cli_lock_writes_root_lockfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_pyproject(
        tmp_path,
        dependencies={"std_path": "jsr:@std/path@^1"},
        commands={},
    )

    code, _stdout, _stderr = run_cli(["lock"], monkeypatch=monkeypatch, cwd=tmp_path, capsys=capsys)

    assert code == 0
    assert (tmp_path / "deno.lock").is_file()


def test_cli_add_updates_pyproject_and_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_pyproject(
        tmp_path,
        dependencies={"std_path": "jsr:@std/path@^1"},
        commands={},
    )

    code, _stdout, _stderr = run_cli(
        ["add", "std_assert", "jsr:@std/assert@^1", "--dev"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    assert code == 0
    document = read_pyproject_document(tmp_path)
    assert document["gdansk"]["dependencies"]["dev"]["std_assert"] == "jsr:@std/assert@^1"
    assert (tmp_path / "deno.lock").is_file()


def test_cli_update_writes_dependency_and_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_pyproject(
        tmp_path,
        dependencies={"is_number": "npm:is-number@6.0.0"},
        commands={},
    )
    code, _stdout, _stderr = run_cli(["lock"], monkeypatch=monkeypatch, cwd=tmp_path, capsys=capsys)
    assert code == 0

    code, _stdout, _stderr = run_cli(
        ["update", "is_number", "--latest"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    assert code == 0
    document = read_pyproject_document(tmp_path)
    assert document["gdansk"]["dependencies"]["is_number"] == "npm:is-number@7.0.0"
    assert (tmp_path / "deno.lock").is_file()


def test_cli_commands_lists_configured_entries(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    code, stdout, _stderr = run_cli(["commands"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "version" in stdout


def test_cli_doctor_passes_for_valid_fixture(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    (project_root / "deno.lock").write_text("{}\n", encoding="utf-8")

    code, stdout, _stderr = run_cli(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "doctor:" in stdout


def test_module_entrypoint_version():
    completed = subprocess.run(
        [sys.executable, "-m", "gdansk", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "gdansk" in completed.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="Vite build loads Rollup's native Node-API addon")
def test_cli_build_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, frontend_root = write_src_layout_project(
        tmp_path,
        dependencies={"vite": "8.0.8"},
        commands={},
    )
    (frontend_root / "index.html").write_text("<main>gdansk</main>\n", encoding="utf-8")

    code, _stdout, _stderr = run_cli(["lock"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)
    assert code == 0
    code, _stdout, _stderr = run_cli(["build"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)
    assert code == 0
    assert (frontend_root / "dist" / "index.html").is_file()


def test_cli_run_package_command(
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


def test_cli_run_watch_stops_on_signal(tmp_path: Path):
    write_pyproject(
        tmp_path,
        dependencies={"zx": "8.5.5"},
        commands={"idle": ["zx", "idle.mjs"]},
    )
    (tmp_path / "idle.mjs").write_text("setInterval(() => {}, 1000);\n", encoding="utf-8")
    subprocess.run(
        [sys.executable, "-m", "gdansk", "lock"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    command = [sys.executable, "-m", "gdansk", "run", "idle", "--watch"]
    if sys.platform == "win32":
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
        time.sleep(1)
        assert process.poll() is None
        stop_signal = signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGTERM
        process.send_signal(stop_signal)
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, (stdout, stderr)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)
