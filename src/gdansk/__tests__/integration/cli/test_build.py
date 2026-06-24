from __future__ import annotations

import sys
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
        dependencies={"vite": "8.0.14"},
        commands={},
    )
    (frontend_root / "index.html").write_text("<main>gdansk</main>\n", encoding="utf-8")

    code, _stdout, _stderr = run_cli(["lock"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)
    assert code == 0
    code, _stdout, _stderr = run_cli(["build"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)
    assert code == 0
    assert (frontend_root / "dist" / "index.html").is_file()
