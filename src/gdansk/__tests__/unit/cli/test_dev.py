from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from belgie.errors import BelgieRuntimeError

from gdansk.__tests__.conftest import run_cli
from gdansk.task import DEFAULT_HOST, DEFAULT_PORT


def test_dev_invokes_internal_vite_command(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, frontend = gdansk_project
    calls: dict[str, Any] = {}

    async def fake_start_command(project, command: str, **kwargs: Any) -> SimpleNamespace:
        calls.update(project=project, command=command, **kwargs)
        return SimpleNamespace()

    async def fake_run_until_signal(awaitable) -> None:
        await awaitable

    monkeypatch.setattr("gdansk.cli.start_command", fake_start_command)
    monkeypatch.setattr("gdansk.cli.dev.run_until_signal", fake_run_until_signal)

    run_cli(["dev"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert calls["command"] == "vite"
    assert calls["cwd"] == frontend
    assert calls["argv"] == [
        "--host",
        DEFAULT_HOST,
        "--port",
        str(DEFAULT_PORT),
    ]


def test_dev_host_and_port_overrides(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    async def fake_start_command(project, command: str, **kwargs: Any) -> SimpleNamespace:
        calls.update(project=project, command=command, **kwargs)
        return SimpleNamespace()

    async def fake_run_until_signal(awaitable) -> None:
        await awaitable

    monkeypatch.setattr("gdansk.cli.start_command", fake_start_command)
    monkeypatch.setattr("gdansk.cli.dev.run_until_signal", fake_run_until_signal)

    run_cli(
        ["dev", "--host", "example.test", "--port", "9000"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert calls["argv"] == ["--host", "example.test", "--port", "9000"]


def test_dev_task_args_passthrough(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    async def fake_start_command(project, command: str, **kwargs: Any) -> SimpleNamespace:
        calls.update(project=project, command=command, **kwargs)
        return SimpleNamespace()

    async def fake_run_until_signal(awaitable) -> None:
        await awaitable

    monkeypatch.setattr("gdansk.cli.start_command", fake_start_command)
    monkeypatch.setattr("gdansk.cli.dev.run_until_signal", fake_run_until_signal)

    run_cli(
        ["dev", "--", "--open"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert calls["argv"][-1] == "--open"


def test_dev_maps_runtime_error_to_exit_1(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    async def fake_start_command(_project, _command: str, **_kwargs: Any) -> SimpleNamespace:
        msg = "dev failed"
        raise BelgieRuntimeError(msg)

    monkeypatch.setattr("gdansk.cli.start_command", fake_start_command)

    code, _stdout, stderr = run_cli(["dev"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "dev failed" in stderr
