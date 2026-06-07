from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gdansk.__tests__.conftest import write_frontend_tree, write_pyproject
from gdansk.cli import main


def _invoke(argv: list[str], *, monkeypatch: pytest.MonkeyPatch, cwd: Path) -> int:
    monkeypatch.chdir(cwd)
    try:
        main(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0
    return 0


@pytest.fixture
def deno_on_path() -> None:
    if shutil.which("deno") is None and not __import__("os").environ.get("GDANSK_DENO"):
        pytest.skip("deno executable is not available")


@pytest.mark.integration
def test_cli_install_writes_root_lockfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    deno_on_path: None,
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_pyproject(
        project_root,
        dependencies={"std_path": "jsr:@std/path@^1"},
    )

    assert _invoke(["install"], monkeypatch=monkeypatch, cwd=project_root) == 0
    assert (project_root / "deno.lock").is_file()


@pytest.mark.integration
def test_cli_lock_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    deno_on_path: None,
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_pyproject(
        project_root,
        dependencies={"std_path": "jsr:@std/path@^1"},
    )
    assert _invoke(["lock"], monkeypatch=monkeypatch, cwd=project_root) == 0
    assert _invoke(["lock"], monkeypatch=monkeypatch, cwd=project_root) == 0


@pytest.mark.integration
def test_cli_scripts_lists_configured_entries(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    assert _invoke(["scripts"], monkeypatch=monkeypatch, cwd=project_root) == 0
    captured = capsys.readouterr()
    assert "build" in captured.out
    assert "dev" in captured.out


@pytest.mark.integration
def test_cli_doctor_passes_for_valid_fixture(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    (project_root / "deno.lock").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr("gdansk.cli._check_deno_available", lambda: ("ok", "deno executable"))
    monkeypatch.chdir(project_root)
    try:
        main(["doctor"])
    except SystemExit as exc:
        assert not isinstance(exc.code, int) or exc.code == 0
    captured = capsys.readouterr()
    assert "doctor:" in captured.out


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
    deno_on_path: None,
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_pyproject(
        project_root,
        dependencies={"std_path": "jsr:@std/path@^1"},
        scripts={"build": "deno eval 'Deno.exit(0)'"},
    )
    write_frontend_tree(project_root)
    assert _invoke(["install"], monkeypatch=monkeypatch, cwd=project_root) == 0
    assert _invoke(["build"], monkeypatch=monkeypatch, cwd=project_root) == 0
