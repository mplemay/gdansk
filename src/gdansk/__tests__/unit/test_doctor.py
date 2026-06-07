from __future__ import annotations

from pathlib import Path

import pytest

from gdansk.__tests__.conftest import write_frontend_tree, write_pyproject
from gdansk.cli import main


def _run_doctor(
    argv: list[str],
    *,
    monkeypatch: pytest.MonkeyPatch,
    cwd: Path,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    monkeypatch.chdir(cwd)
    exit_code = 0
    try:
        main(argv)
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 0
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_doctor_passes_for_valid_project(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    (project_root / "deno.lock").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr("gdansk.cli._check_deno_available", lambda: ("ok", "deno executable (/usr/bin/deno)"))

    code, stdout, _stderr = _run_doctor(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "ok   Python" in stdout
    assert "all checks passed" in stdout


def test_doctor_fails_when_deno_missing(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    monkeypatch.setattr(
        "gdansk.cli._check_deno_available",
        lambda: ("fail", "deno executable not found on PATH"),
    )

    code, _stdout, stderr = _run_doctor(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "doctor: 1 check(s) failed" in stderr


def test_doctor_fails_without_dependencies_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_pyproject(project_root, dependencies={})
    write_frontend_tree(project_root)
    monkeypatch.setattr("gdansk.cli._check_deno_available", lambda: ("ok", "deno executable"))

    code, stdout, _stderr = _run_doctor(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "fail No [gdansk.dependencies]" in stdout


def test_doctor_fails_without_frontend_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_pyproject(project_root, frontend=None)
    monkeypatch.setattr("gdansk.cli._check_deno_available", lambda: ("ok", "deno executable"))

    code, stdout, _stderr = _run_doctor(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "fail" in stdout
    assert "--frontend" in stdout


def test_doctor_fails_without_vite_config(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, frontend_root = gdansk_project
    (frontend_root / "vite.config.ts").unlink()
    monkeypatch.setattr("gdansk.cli._check_deno_available", lambda: ("ok", "deno executable"))

    code, stdout, _stderr = _run_doctor(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "fail" in stdout
    assert "vite.config.ts" in stdout


def test_doctor_warns_when_root_lock_missing(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    monkeypatch.setattr("gdansk.cli._check_deno_available", lambda: ("ok", "deno executable"))

    code, stdout, stderr = _run_doctor(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "warn deno.lock missing" in stdout
    assert "warning:" in stderr


def test_doctor_warns_about_legacy_frontend_lock(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, frontend_root = gdansk_project
    (frontend_root / "deno.lock").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr("gdansk.cli._check_deno_available", lambda: ("ok", "deno executable"))

    code, stdout, stderr = _run_doctor(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "Legacy deno.lock" in stdout
    assert "warning:" in stderr


def test_doctor_warns_when_scripts_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_pyproject(project_root, scripts={"build": "vite build"})
    write_frontend_tree(project_root)
    monkeypatch.setattr("gdansk.cli._check_deno_available", lambda: ("ok", "deno executable"))

    code, stdout, stderr = _run_doctor(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "warn Missing [gdansk.scripts].dev" in stdout
    assert "warning:" in stderr
