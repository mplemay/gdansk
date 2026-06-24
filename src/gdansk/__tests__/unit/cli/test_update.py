from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from belgie.errors import BelgieRuntimeError

from gdansk.__tests__.conftest import run_cli


def test_update_dispatches_packages_and_latest(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    def fake_update_project(project, packages, *, latest: bool) -> SimpleNamespace:
        calls.update(project=project, packages=packages, latest=latest)
        return SimpleNamespace(
            lockfile=str(project_root / "deno.lock"),
            changes=[SimpleNamespace(name="vite", previous="npm:vite@8", updated="npm:vite@9")],
        )

    monkeypatch.setattr("gdansk.cli.update_project", fake_update_project)

    code, stdout, _stderr = run_cli(
        ["update", "vite", "react", "--latest"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert code == 0
    assert calls["packages"] == ["vite", "react"]
    assert calls["latest"] is True
    assert "vite: npm:vite@8 -> npm:vite@9" in stdout
    assert str(project_root / "deno.lock") in stdout


def test_update_without_latest_flag(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    def fake_update_project(project, packages, *, latest: bool) -> SimpleNamespace:
        calls.update(project=project, packages=packages, latest=latest)
        return SimpleNamespace(lockfile=str(project_root / "deno.lock"), changes=[])

    monkeypatch.setattr("gdansk.cli.update_project", fake_update_project)

    run_cli(
        ["update", "vite"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert calls["packages"] == ["vite"]
    assert calls["latest"] is False


def test_update_maps_runtime_error_to_exit_1(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    def fake_update_project(_project, _packages, *, latest: bool) -> SimpleNamespace:
        msg = "update failed"
        raise BelgieRuntimeError(msg)

    monkeypatch.setattr("gdansk.cli.update_project", fake_update_project)

    code, _stdout, stderr = run_cli(
        ["update", "vite", "--latest"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert code == 1
    assert "update failed" in stderr
