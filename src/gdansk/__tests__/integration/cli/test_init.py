from __future__ import annotations

from pathlib import Path

import pytest

from gdansk.__tests__.conftest import run_cli, stage_init_vite_package
from gdansk._project import read_pyproject_document

pytestmark = pytest.mark.integration


def test_init_creates_scaffold_and_lockfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    target = tmp_path / "new-project"
    stage_init_vite_package(target)

    code, stdout, _stderr = run_cli(
        ["init", "--path", str(target)],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    assert code == 0
    assert "Initialized gdansk project" in stdout
    assert (target / "src" / "my_mcp_server" / "__main__.py").exists()
    assert not (target / "src" / "my_mcp_server" / "views" / "vite.config.ts").exists()
    assert (target / "src" / "my_mcp_server" / "views" / "widgets" / "hello" / "widget.tsx").exists()
    document = read_pyproject_document(target)
    assert "dependencies" in document["gdansk"]
    assert (target / "deno.lock").is_file()
