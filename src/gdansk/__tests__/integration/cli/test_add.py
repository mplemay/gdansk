from __future__ import annotations

from pathlib import Path

import pytest

from gdansk.__tests__.conftest import run_cli, write_pyproject
from gdansk._project import read_pyproject_document

pytestmark = pytest.mark.integration


def test_add_updates_pyproject_and_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_pyproject(
        tmp_path,
        dependencies={"std_path": "jsr:@std/path@^1"},
        commands={},
    )

    code, stdout, _stderr = run_cli(
        ["add", "std_assert", "jsr:@std/assert@^1", "--dev"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    assert code == 0
    assert "std_assert" in stdout
    document = read_pyproject_document(tmp_path)
    assert document["gdansk"]["dependencies"]["dev"]["std_assert"] == "jsr:@std/assert@^1"
    assert (tmp_path / "deno.lock").is_file()
