from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from gdansk.vite import Vite

if TYPE_CHECKING:
    from pathlib import Path

    from gdansk.task import CommandProcess


def test_vite_rejects_invalid_runtime_port(views_path: Path):
    with pytest.raises(ValueError, match="runtime port"):
        Vite(views_path, port=0)


def test_vite_rejects_missing_root(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="frontend root"):
        Vite(tmp_path / "missing")


def test_vite_rejects_invalid_build_directory(views_path: Path):
    with pytest.raises(ValueError, match="build directory"):
        Vite(views_path, build_directory="../public")


def test_vite_owns_frontend_paths(views_path: Path):
    vite = Vite(views_path, build_directory="public/ui")

    assert vite.build_directory == "public/ui"
    assert vite.build_directory_path == views_path / "public/ui"
    assert vite.manifest_path == views_path / "public/ui" / "gdansk-manifest.json"
    assert vite.root == views_path
    assert vite.widgets_root == views_path / "widgets"


def test_vite_has_no_runtime_by_default(views_path: Path):
    vite = Vite(views_path)

    assert vite.has_runtime() is False
    assert not hasattr(vite, "_deno")


async def test_vite_dev_start_uses_widget_command(
    views_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] | None = None

    class FakeCommandProcess:
        is_running = True

        def __init__(self) -> None:
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

    async def fake_start_widget(start: Path, argv: list[str], *, local_source: str) -> FakeCommandProcess:
        nonlocal captured
        captured = {"argv": argv, "source": local_source, "start": start}
        return FakeCommandProcess()

    vite = Vite(views_path)
    monkeypatch.setattr("gdansk.vite.start_widget_command", fake_start_widget)

    await vite.start_dev()

    frontend = vite._frontend
    assert isinstance(frontend, FakeCommandProcess)
    assert captured is not None
    assert captured["start"] == views_path
    assert cast("list[str]", captured["argv"])[:3] == ["dev", "--root", str(views_path)]
    assert "startDevelopment" in cast("str", captured["source"])
    assert 'host: "127.0.0.1"' in cast("str", captured["source"])
    assert "port: 13714" in cast("str", captured["source"])
    assert vite.has_runtime() is True
    assert not hasattr(vite, "_deno")

    await vite.stop()

    assert frontend.stopped is True
    assert vite.has_runtime() is False


async def test_vite_start_dev_restarts_after_process_exit(
    views_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    start_calls = 0

    class FakeCommandProcess:
        def __init__(self, *, running: bool) -> None:
            self.origin = "http://127.0.0.1:13714"
            self._running = running
            self.stopped = False

        @property
        def is_running(self) -> bool:
            return self._running

        async def stop(self) -> None:
            self.stopped = True

    async def fake_start_widget(start: Path, argv: list[str], *, local_source: str) -> FakeCommandProcess:
        nonlocal start_calls
        _ = start, argv, local_source
        start_calls += 1
        return FakeCommandProcess(running=True)

    vite = Vite(views_path)
    monkeypatch.setattr("gdansk.vite.start_widget_command", fake_start_widget)
    vite._frontend = cast("CommandProcess", FakeCommandProcess(running=False))

    await vite.start_dev()

    assert start_calls == 1
    assert vite.has_runtime() is True
    await vite.stop()


def test_vite_defaults_to_views_under_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    views = tmp_path / "views"
    views.mkdir()
    monkeypatch.chdir(tmp_path)

    vite = Vite()

    assert vite.root == views
    assert vite.build_directory == "dist"
    assert vite.build_directory_path == views / "dist"
    assert vite.widgets_root == views / "widgets"
