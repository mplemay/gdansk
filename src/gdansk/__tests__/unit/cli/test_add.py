from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from belgie.errors import BelgieRuntimeError

from gdansk.__tests__.conftest import run_cli


def test_add_dispatches_alias_specifier_and_dev_group(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    def fake_add_dependency(project, **kwargs: Any) -> SimpleNamespace:
        calls["project"] = project
        calls.update(kwargs)
        return SimpleNamespace(lockfile=str(project_root / "deno.lock"), dependencies=2)

    monkeypatch.setattr("gdansk.cli.add_dependency", fake_add_dependency)

    code, stdout, _stderr = run_cli(
        ["add", "react", "^20", "--dev"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert code == 0
    assert calls["project"].root == project_root
    assert calls["alias"] == "react"
    assert calls["specifier"] == "^20"
    assert calls["dev"] is True
    assert "Added react to dev dependencies" in stdout
    assert str(project_root / "deno.lock") in stdout


def test_add_default_group_message(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    def fake_add_dependency(_project, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(lockfile=str(project_root / "deno.lock"), dependencies=1)

    monkeypatch.setattr("gdansk.cli.add_dependency", fake_add_dependency)

    _code, stdout, _stderr = run_cli(
        ["add", "react", "^20"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert "Added react to default dependencies" in stdout


def test_add_maps_runtime_error_to_exit_1(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    def fake_add_dependency(_project, **_kwargs: Any) -> SimpleNamespace:
        msg = "add failed"
        raise BelgieRuntimeError(msg)

    monkeypatch.setattr("gdansk.cli.add_dependency", fake_add_dependency)

    code, _stdout, stderr = run_cli(
        ["add", "react", "^20"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert code == 1
    assert "add failed" in stderr
