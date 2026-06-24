from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from gdansk.__tests__.conftest import run_cli
from gdansk.cli import main


def test_version_prints_package_version(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert "gdansk" in capsys.readouterr().out


def test_help_lists_package_commands(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    for command in ("add", "lock", "update", "build", "dev", "run", "commands", "doctor", "init"):
        assert command in output
    assert "install" not in output


def test_unknown_subcommand_exits_with_usage_error(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc:
        main(["not-a-command"])

    assert exc.value.code == 2


def test_project_error_maps_to_exit_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["lock"])

    assert exc.value.code == 1
    assert "pyproject.toml" in capsys.readouterr().err


def test_task_args_passed_through_to_command(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _frontend = gdansk_project
    calls: dict[str, Any] = {}

    async def fake_run_command(project, command: str, **kwargs: Any) -> None:
        calls.update(project=project, command=command, **kwargs)

    monkeypatch.setattr("gdansk.cli.run_command", fake_run_command)

    run_cli(
        ["build", "--", "x"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert calls["argv"] == ["build", "x"]
