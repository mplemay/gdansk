from __future__ import annotations

from pathlib import Path

import pytest
from belgie.errors import BelgieRuntimeError

from gdansk.__tests__.conftest import run_cli, write_src_layout_project


def test_build_invokes_isolated_widget_runtime(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root, frontend = gdansk_project
    calls: list[Path] = []

    class FakeVite:
        def __init__(self, root: Path) -> None:
            calls.append(root)

        async def build(self) -> None:
            return None

    monkeypatch.setattr("gdansk.cli.build.Vite", FakeVite)
    code, _stdout, _stderr = run_cli(["build"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert calls == [frontend]


def test_build_project_option_resolves_alternate_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root, frontend = write_src_layout_project(tmp_path / "nested")
    calls: list[Path] = []

    class FakeVite:
        def __init__(self, root: Path) -> None:
            calls.append(root)

        async def build(self) -> None:
            return None

    monkeypatch.setattr("gdansk.cli.build.Vite", FakeVite)
    run_cli(["build", "--project", str(project_root)], monkeypatch=monkeypatch, cwd=tmp_path, capsys=capsys)
    assert calls == [frontend]


def test_build_maps_runtime_error_to_exit_1(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root, _ = gdansk_project

    class FakeVite:
        def __init__(self, _root: Path) -> None:
            pass

        async def build(self) -> None:
            msg = "build failed"
            raise BelgieRuntimeError(msg)

    monkeypatch.setattr("gdansk.cli.build.Vite", FakeVite)
    code, _stdout, stderr = run_cli(["build"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)
    assert code == 1
    assert "build failed" in stderr
