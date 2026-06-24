from __future__ import annotations

from pathlib import Path

import pytest

from gdansk.__tests__.conftest import run_cli, write_pyproject
from gdansk._project import read_pyproject_document

pytestmark = pytest.mark.integration


def test_update_writes_dependency_and_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_pyproject(
        tmp_path,
        dependencies={"is_number": "npm:is-number@6.0.0"},
        commands={},
    )
    code, _stdout, _stderr = run_cli(["lock"], monkeypatch=monkeypatch, cwd=tmp_path, capsys=capsys)
    assert code == 0

    code, _stdout, _stderr = run_cli(
        ["update", "is_number", "--latest"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    assert code == 0
    document = read_pyproject_document(tmp_path)
    assert document["gdansk"]["dependencies"]["is_number"] == "npm:is-number@7.0.0"
    assert (tmp_path / "deno.lock").is_file()
