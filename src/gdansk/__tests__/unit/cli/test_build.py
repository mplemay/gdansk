from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from belgie.errors import BelgieRuntimeError

from gdansk.__tests__.conftest import run_cli, write_src_layout_project


def test_build_invokes_internal_vite_command(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, frontend = gdansk_project
    calls: dict[str, Any] = {}

    async def fake_run_command(project, command: str, **kwargs: Any) -> None:
        calls.update(project=project, command=command, **kwargs)

    monkeypatch.setattr("gdansk.cli.run_command", fake_run_command)

    run_cli(
        ["build", "--", "--emptyOutDir"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert calls["command"] == "vite"
    assert calls["cwd"] == frontend
    assert calls["argv"] == ["build", "--emptyOutDir"]


def test_build_frontend_option_overrides_cwd(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, frontend = gdansk_project
    calls: dict[str, Any] = {}

    async def fake_run_command(project, command: str, **kwargs: Any) -> None:
        calls.update(project=project, command=command, **kwargs)

    monkeypatch.setattr("gdansk.cli.run_command", fake_run_command)

    run_cli(
        ["build", "--frontend", str(frontend)],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert calls["cwd"] == frontend


def test_build_project_option_resolves_alternate_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, frontend = write_src_layout_project(tmp_path / "nested")
    calls: dict[str, Any] = {}

    async def fake_run_command(project, command: str, **kwargs: Any) -> None:
        calls.update(project=project, command=command, **kwargs)

    monkeypatch.setattr("gdansk.cli.run_command", fake_run_command)

    run_cli(
        ["build", "--project", str(project_root)],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    assert calls["project"].root == project_root
    assert calls["cwd"] == frontend


def test_build_maps_runtime_error_to_exit_1(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    async def fake_run_command(_project, _command: str, **_kwargs: Any) -> None:
        msg = "build failed"
        raise BelgieRuntimeError(msg)

    monkeypatch.setattr("gdansk.cli.run_command", fake_run_command)

    code, _stdout, stderr = run_cli(["build"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "build failed" in stderr
