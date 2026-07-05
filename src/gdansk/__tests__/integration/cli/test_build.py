from __future__ import annotations

import sys
from json import loads
from pathlib import Path

import pytest

from gdansk.__tests__.conftest import run_cli, write_src_layout_project

pytestmark = pytest.mark.integration


@pytest.mark.skipif(sys.platform == "win32", reason="Vite build loads Rollup's native Node-API addon")
def test_build_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, frontend_root = write_src_layout_project(
        tmp_path,
        commands={},
    )
    code, _stdout, _stderr = run_cli(["lock"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)
    assert code == 0
    code, _stdout, _stderr = run_cli(["build"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)
    assert code == 0
    manifest = loads((frontend_root / "dist" / "gdansk-manifest.json").read_text(encoding="utf-8"))
    assert manifest["widgets"]["hello"]["entry"] == "hello/widget.tsx"
    html = manifest["widgets"]["hello"]["html"]
    assert html.startswith("<!DOCTYPE html>")
    assert '<script type="module" src=' not in html
    for server_only_import in (
        "@gdansk/widget/dist/assets/build",
        "@tailwindcss/vite",
        "@vitejs/plugin-react",
        "node:fs",
        "node:perf_hooks",
        "node:url",
    ):
        assert server_only_import not in html
    assert list((frontend_root / "dist").iterdir()) == [frontend_root / "dist" / "gdansk-manifest.json"]
