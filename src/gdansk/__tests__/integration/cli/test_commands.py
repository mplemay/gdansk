from __future__ import annotations

from pathlib import Path

import pytest

from gdansk.__tests__.conftest import run_cli

pytestmark = pytest.mark.integration


def test_commands_lists_configured_entries(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    code, stdout, _stderr = run_cli(["commands"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "version" in stdout
    assert "vite --version" in stdout
