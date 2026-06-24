from __future__ import annotations

import importlib.metadata
from pathlib import Path

import pytest
import typer
from typer.core import TyperGroup

from gdansk.__tests__.conftest import run_cli
from gdansk.cli.__main__ import app


def test_version_prints_package_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    code, stdout, _stderr = run_cli(["--version"], monkeypatch=monkeypatch, cwd=tmp_path, capsys=capsys)

    assert code == 0
    assert f"gdansk {importlib.metadata.version('gdansk')}" in stdout


def test_help_lists_package_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    code, stdout, _stderr = run_cli(["--help"], monkeypatch=monkeypatch, cwd=tmp_path, capsys=capsys)

    assert code == 0
    group = typer.main.get_command(app)
    assert isinstance(group, TyperGroup)
    for command in group.commands:
        assert command in stdout
    assert "install" not in stdout


def test_unknown_subcommand_exits_with_usage_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    code, _stdout, _stderr = run_cli(
        ["not-a-command"],
        monkeypatch=monkeypatch,
        cwd=tmp_path,
        capsys=capsys,
    )

    assert code == 2


def test_project_error_maps_to_exit_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    code, _stdout, stderr = run_cli(["lock"], monkeypatch=monkeypatch, cwd=tmp_path, capsys=capsys)

    assert code == 1
    assert "pyproject.toml" in stderr
