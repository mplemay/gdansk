from __future__ import annotations

from pathlib import Path

import pytest

from gdansk.__tests__.conftest import run_cli

pytestmark = pytest.mark.integration


def test_doctor_passes_for_valid_fixture(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    (project_root / "deno.lock").write_text("{}\n", encoding="utf-8")

    code, stdout, _stderr = run_cli(["doctor"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "all checks passed" in stdout
