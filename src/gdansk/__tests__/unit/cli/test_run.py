from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from gdansk.__tests__.conftest import run_cli


def test_run_executes_configured_argument_array(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    async def fake_run_command(project, command: str, **kwargs: Any) -> None:
        calls.update(project=project, command=command, **kwargs)

    monkeypatch.setattr("gdansk.cli.run_command", fake_run_command)

    run_cli(
        ["run", "version", "--", "--debug"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert calls["command"] == "vite"
    assert calls["cwd"] == project_root
    assert calls["argv"] == ["--version", "--debug"]


def test_run_unknown_command_lists_available_commands(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    code, _stdout, stderr = run_cli(["run", "missing"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "Available commands" in stderr
    assert "version" in stderr


def test_run_watch_uses_start_command_and_run_until_signal(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    start_calls: dict[str, Any] = {}
    signal_calls: list[Any] = []

    async def fake_start_command(project, command: str, **kwargs: Any) -> SimpleNamespace:
        start_calls.update(project=project, command=command, **kwargs)
        return SimpleNamespace()

    async def fake_run_until_signal(awaitable) -> None:
        signal_calls.append(awaitable)
        await awaitable

    monkeypatch.setattr("gdansk.cli.start_command", fake_start_command)
    monkeypatch.setattr("gdansk.cli.run.run_until_signal", fake_run_until_signal)

    run_cli(
        ["run", "version", "--watch"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert start_calls["command"] == "vite"
    assert start_calls["argv"] == ["--version"]
    assert len(signal_calls) == 1
