from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from gdansk.vite import Vite

if TYPE_CHECKING:
    from pathlib import Path


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

    assert vite.assets_path == "/public/ui"
    assert vite.build_directory == "public/ui"
    assert vite.build_directory_path == views_path / "public/ui"
    assert vite.manifest_path == views_path / "public/ui" / "gdansk-manifest.json"
    assert vite.root == views_path
    assert vite.widgets_root == views_path / "widgets"


def test_vite_has_no_runtime_by_default(views_path: Path):
    vite = Vite(views_path)

    assert vite.has_runtime() is False
    assert not hasattr(vite, "_deno")


async def test_vite_dev_start_uses_embedded_frontend_runtime(
    views_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: tuple[Path, str, int] | None = None

    class FakeFrontendDevServer:
        origin = "http://127.0.0.1:13714"

        def __init__(self) -> None:
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

    async def fake_start_frontend_dev(root: Path, host: str, port: int) -> FakeFrontendDevServer:
        nonlocal captured
        captured = (root, host, port)
        return FakeFrontendDevServer()

    vite = Vite(views_path)
    monkeypatch.setattr("gdansk.vite.start_frontend_dev", fake_start_frontend_dev)

    await vite.start_dev()

    frontend = vite._frontend
    assert isinstance(frontend, FakeFrontendDevServer)
    assert captured == (views_path, "127.0.0.1", 13714)
    assert vite.require_origin() == "http://127.0.0.1:13714"
    assert vite.has_runtime() is True
    assert not hasattr(vite, "_deno")

    await vite.stop()

    assert frontend.stopped is True
    assert vite.has_runtime() is False


def test_vite_defaults_to_views_under_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    views = tmp_path / "views"
    views.mkdir()
    monkeypatch.chdir(tmp_path)

    vite = Vite()

    assert vite.root == views
    assert vite.assets_path == "/dist"
    assert vite.build_directory == "dist"
    assert vite.build_directory_path == views / "dist"
    assert vite.widgets_root == views / "widgets"
