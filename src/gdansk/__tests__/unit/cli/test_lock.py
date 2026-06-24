from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from belgie.errors import BelgieRuntimeError

from gdansk.__tests__.conftest import run_cli


def test_lock_dispatches_project(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: list[Path] = []

    def fake_lock_project(project) -> SimpleNamespace:
        calls.append(project.root)
        return SimpleNamespace(lockfile=str(project_root / "deno.lock"), dependencies=1)

    monkeypatch.setattr("gdansk.cli.lock_project", fake_lock_project)

    code, stdout, _stderr = run_cli(["lock"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert calls == [project_root]
    assert "Locked 1 dependencies" in stdout
    assert str(project_root / "deno.lock") in stdout


def test_lock_maps_runtime_error_to_exit_1(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    def fake_lock_project(_project) -> SimpleNamespace:
        msg = "lock failed"
        raise BelgieRuntimeError(msg)

    monkeypatch.setattr("gdansk.cli.lock_project", fake_lock_project)

    code, _stdout, stderr = run_cli(["lock"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "lock failed" in stderr
