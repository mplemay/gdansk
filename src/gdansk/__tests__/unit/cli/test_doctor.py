from __future__ import annotations

from pathlib import Path

import pytest

from gdansk.__tests__.conftest import run_cli, write_src_layout_project


def test_doctor_passes_for_valid_project(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    (project_root / "deno.lock").write_text("{}\n", encoding="utf-8")

    code, stdout, _stderr = run_cli(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "ok   [gdansk.dependencies]" in stdout
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
    assert "fail No [gdansk.dependencies]" in stdout


def test_doctor_fails_without_widget_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_src_layout_project(
        project_root,
        dependencies={"react": "^19", "react-dom": "^19", "vite": ">=8.1,<9"},
    )

    code, stdout, _stderr = run_cli(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "Required gdansk dependency '@gdansk/widget' is missing" in stdout


def test_doctor_warns_when_root_lock_missing(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    code, _stdout, stderr = run_cli(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "warning: gdansk lockfile (deno.lock) missing" in stderr


def test_doctor_warns_about_legacy_frontend_lock(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, frontend_root = gdansk_project
    (frontend_root / "deno.lock").write_text("{}\n", encoding="utf-8")

    code, _stdout, stderr = run_cli(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "warning: Legacy lockfile found under frontend" in stderr


def test_doctor_fails_when_project_not_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    code, stdout, _stderr = run_cli(["doctor"], monkeypatch=monkeypatch, cwd=tmp_path, capsys=capsys)

    assert code == 1
    assert "fail Could not find pyproject.toml" in stdout


def test_doctor_fails_when_frontend_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    write_src_layout_project(project_root)
    frontend = project_root / "src" / "example" / "views"
    for child in frontend.iterdir():
        if child.is_file():
            child.unlink()
        else:
            for nested in child.rglob("*"):
                if nested.is_file():
                    nested.unlink()
            for nested in sorted(child.rglob("*"), reverse=True):
                if nested.is_dir():
                    nested.rmdir()
            child.rmdir()
    frontend.rmdir()

    code, stdout, _stderr = run_cli(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "fail Frontend root does not exist" in stdout
