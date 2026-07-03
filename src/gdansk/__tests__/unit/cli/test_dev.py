from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from belgie.errors import BelgieRuntimeError

from gdansk.__tests__.conftest import run_cli


def test_dev_starts_isolated_widget_runtime(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root, frontend = gdansk_project
    calls: list[tuple[Path, str, int]] = []

    class FakeVite:
        def __init__(self, root: Path, *, host: str, port: int) -> None:
            calls.append((root, host, port))

        async def start_dev(self) -> SimpleNamespace:
            return SimpleNamespace()

    async def fake_run_until_signal(awaitable) -> None:
        await awaitable

    monkeypatch.setattr("gdansk.cli.dev.Vite", FakeVite)
    monkeypatch.setattr("gdansk.cli.dev.run_until_signal", fake_run_until_signal)
    code, _stdout, _stderr = run_cli(
        ["dev", "--host", "example.test", "--port", "9000"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )
    assert code == 0
    assert calls == [(frontend, "example.test", 9000)]


def test_dev_maps_runtime_error_to_exit_1(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root, _ = gdansk_project

    class FakeVite:
        def __init__(self, _root: Path, *, host: str, port: int) -> None:
            _ = host, port

        async def start_dev(self) -> SimpleNamespace:
            msg = "dev failed"
            raise BelgieRuntimeError(msg)

    monkeypatch.setattr("gdansk.cli.dev.Vite", FakeVite)
    code, _stdout, stderr = run_cli(["dev"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)
    assert code == 1
    assert "dev failed" in stderr
