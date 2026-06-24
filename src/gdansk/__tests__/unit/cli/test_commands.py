from __future__ import annotations

from pathlib import Path

import pytest

from gdansk.__tests__.conftest import run_cli, write_pyproject


def test_commands_lists_argument_arrays(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    code, stdout, _stderr = run_cli(["commands"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "version" in stdout
    assert "vite --version" in stdout


def test_commands_empty_table_exits_with_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_pyproject(tmp_path, commands={})

    code, _stdout, stderr = run_cli(["commands"], monkeypatch=monkeypatch, cwd=tmp_path, capsys=capsys)

    assert code == 1
    assert "No [gdansk.commands] entries configured." in stderr
