from __future__ import annotations

from pathlib import Path

import pytest

from gdansk.__tests__.conftest import run_cli, write_pyproject, write_src_layout_project


def test_doctor_passes_for_valid_project(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    (project_root / "deno.lock").write_text("{}\n", encoding="utf-8")

    code, stdout, _stderr = run_cli(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "ok   Python" in stdout
    assert "all checks passed" in stdout


def test_doctor_fails_without_dependencies_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_src_layout_project(project_root, dependencies={})

    code, stdout, _stderr = run_cli(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "fail No [belgie.dependencies]" in stdout


def test_doctor_fails_without_frontend_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_pyproject(project_root)

    code, stdout, _stderr = run_cli(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "fail" in stdout
    assert "Frontend root does not exist" in stdout


def test_doctor_fails_without_vite_config(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, frontend_root = gdansk_project
    (frontend_root / "vite.config.ts").unlink()

    code, stdout, _stderr = run_cli(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "fail" in stdout
    assert "vite.config.ts" in stdout


def test_doctor_warns_when_root_lock_missing(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    code, stdout, stderr = run_cli(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "warn belgie lockfile (deno.lock) missing" in stdout
    assert "warning:" in stderr


def test_doctor_warns_about_legacy_frontend_lock(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, frontend_root = gdansk_project
    (frontend_root / "deno.lock").write_text("{}\n", encoding="utf-8")

    code, stdout, stderr = run_cli(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "Legacy belgie lockfile (deno.lock)" in stdout
    assert "warning:" in stderr


def test_doctor_warns_when_scripts_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_src_layout_project(project_root, scripts={"build": "vite build"})

    code, stdout, stderr = run_cli(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "warn Missing [belgie.scripts].dev" in stdout
    assert "warning:" in stderr
