from __future__ import annotations

import signal
import subprocess
import sys
import time
from json import dumps
from pathlib import Path

import pytest

from gdansk.__tests__.conftest import run_cli, write_pyproject, write_src_layout_project


def _python_command(source: str) -> str:
    return f"{dumps(sys.executable)} -c {dumps(source)}"


@pytest.mark.integration
def test_cli_install_writes_root_lockfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_pyproject(
        project_root,
        dependencies={"std_path": "jsr:@std/path@^1"},
    )

    code, _stdout, _stderr = run_cli(["install"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)
    assert code == 0
    assert (project_root / "deno.lock").is_file()


@pytest.mark.integration
def test_cli_lock_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_pyproject(
        project_root,
        dependencies={"std_path": "jsr:@std/path@^1"},
    )
    code, _stdout, _stderr = run_cli(["lock"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)
    assert code == 0
    code, _stdout, _stderr = run_cli(["lock"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)
    assert code == 0


@pytest.mark.integration
def test_cli_scripts_lists_configured_entries(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    code, stdout, _stderr = run_cli(["scripts"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)
    assert code == 0
    assert "build" in stdout
    assert "dev" in stdout


@pytest.mark.integration
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


@pytest.mark.integration
def test_module_entrypoint_version():
    completed = subprocess.run(
        [sys.executable, "-m", "gdansk", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "gdansk" in completed.stdout


@pytest.mark.integration
def test_cli_build_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_src_layout_project(
        project_root,
        dependencies={"std_path": "jsr:@std/path@^1"},
        scripts={"build": _python_command("import sys; sys.exit(0)")},
    )
    code, _stdout, _stderr = run_cli(["install"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)
    assert code == 0
    code, _stdout, _stderr = run_cli(["build"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)
    assert code == 0


@pytest.mark.integration
def test_cli_build_from_nested_frontend_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    _, frontend_root = write_src_layout_project(
        project_root,
        package="example",
        dependencies={"std_path": "jsr:@std/path@^1"},
        scripts={"build": _python_command("import sys; sys.exit(0)")},
    )

    code, _stdout, _stderr = run_cli(["install"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)
    assert code == 0
    code, _stdout, _stderr = run_cli(["build"], monkeypatch=monkeypatch, cwd=frontend_root, capsys=capsys)
    assert code == 0


@pytest.mark.integration
def test_cli_run_watch_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_src_layout_project(
        project_root,
        dependencies={"std_path": "jsr:@std/path@^1"},
        scripts={
            "build": _python_command("import sys; sys.exit(0)"),
            "idle": _python_command("import time; time.sleep(60)"),
        },
    )
    code, _stdout, _stderr = run_cli(["install"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)
    assert code == 0

    command = [sys.executable, "-m", "gdansk", "run", "idle", "--watch"]
    if sys.platform == "win32":
        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=project_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    try:
        time.sleep(1)
        assert process.poll() is None
        stop_signal = signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGTERM
        process.send_signal(stop_signal)
        if sys.platform == "win32":
            process.wait(timeout=30)
            assert process.returncode == 0
        else:
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0
            assert "both host and port" not in stderr
            assert "both host and port" not in stdout
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
