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
