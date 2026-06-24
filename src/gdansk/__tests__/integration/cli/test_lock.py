from __future__ import annotations

from pathlib import Path

import pytest

from gdansk.__tests__.conftest import run_cli, write_pyproject

pytestmark = pytest.mark.integration


def test_lock_writes_root_lockfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_pyproject(
        tmp_path,
        dependencies={"std_path": "jsr:@std/path@^1"},
        commands={},
    )

    code, _stdout, _stderr = run_cli(["lock"], monkeypatch=monkeypatch, cwd=tmp_path, capsys=capsys)

    assert code == 0
    assert (tmp_path / "deno.lock").is_file()
