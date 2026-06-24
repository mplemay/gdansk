from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from belgie.errors import BelgieRuntimeError

from gdansk.__tests__.conftest import run_cli
from gdansk.cli import main
from gdansk.task import DEFAULT_HOST, DEFAULT_PORT


def test_version_prints_package_version(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert "gdansk" in capsys.readouterr().out


def test_help_lists_new_package_commands(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "add" in output
    assert "lock" in output
    assert "install" not in output


def test_add_dispatches_alias_specifier_and_group(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    def fake_add_dependency(project, **kwargs: Any) -> SimpleNamespace:
        calls["project"] = project
        calls.update(kwargs)
        return SimpleNamespace(lockfile=str(project_root / "deno.lock"), dependencies=2)

    monkeypatch.setattr("gdansk.cli.add_dependency", fake_add_dependency)

    code, stdout, _stderr = run_cli(
        ["add", "react", "^20", "--dev"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert code == 0
    assert calls["project"].root == project_root
    assert calls["alias"] == "react"
    assert calls["specifier"] == "^20"
    assert calls["dev"] is True
    assert "Added react to dev dependencies" in stdout


def test_lock_dispatches_project(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: list[Path] = []

    def fake_lock_project(project) -> SimpleNamespace:
        calls.append(project.root)
        return SimpleNamespace(lockfile=str(project_root / "deno.lock"), dependencies=1)

    monkeypatch.setattr("gdansk.cli.lock_project", fake_lock_project)

    code, stdout, _stderr = run_cli(["lock"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert calls == [project_root]
    assert "Locked 1 dependencies" in stdout


def test_update_dispatches_packages_and_latest(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    def fake_update_project(project, packages, *, latest: bool) -> SimpleNamespace:
        calls.update(project=project, packages=packages, latest=latest)
        return SimpleNamespace(
            lockfile=str(project_root / "deno.lock"),
            changes=[SimpleNamespace(name="vite", previous="npm:vite@8", updated="npm:vite@9")],
        )

    monkeypatch.setattr("gdansk.cli.update_project", fake_update_project)

    run_cli(
        ["update", "vite", "react", "--latest"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert calls["packages"] == ["vite", "react"]
    assert calls["latest"] is True


def test_lock_maps_runtime_error_to_exit_1(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    def fake_lock_project(_project) -> SimpleNamespace:
        msg = "lock failed"
        raise BelgieRuntimeError(msg)

    monkeypatch.setattr("gdansk.cli.lock_project", fake_lock_project)

    code, _stdout, stderr = run_cli(["lock"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "lock failed" in stderr


def test_build_invokes_internal_vite_command(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, frontend = gdansk_project
    calls: dict[str, Any] = {}

    async def fake_run_command(project, command: str, **kwargs: Any) -> None:
        calls.update(project=project, command=command, **kwargs)

    monkeypatch.setattr("gdansk.cli.run_command", fake_run_command)

    run_cli(
        ["build", "--", "--emptyOutDir"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert calls["command"] == "vite"
    assert calls["cwd"] == frontend
    assert calls["argv"] == ["build", "--emptyOutDir"]


def test_dev_invokes_internal_vite_command(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, frontend = gdansk_project
    calls: dict[str, Any] = {}

    async def fake_start_command(project, command: str, **kwargs: Any) -> SimpleNamespace:
        calls.update(project=project, command=command, **kwargs)
        return SimpleNamespace()

    async def fake_run_until_signal(awaitable) -> None:
        await awaitable

    monkeypatch.setattr("gdansk.cli.start_command", fake_start_command)
    monkeypatch.setattr("gdansk.cli.dev.run_until_signal", fake_run_until_signal)

    run_cli(["dev"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert calls["command"] == "vite"
    assert calls["cwd"] == frontend
    assert calls["argv"] == [
        "--host",
        DEFAULT_HOST,
        "--port",
        str(DEFAULT_PORT),
    ]


def test_run_executes_configured_argument_array(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    async def fake_run_command(project, command: str, **kwargs: Any) -> None:
        calls.update(project=project, command=command, **kwargs)

    monkeypatch.setattr("gdansk.cli.run_command", fake_run_command)

    run_cli(
        ["run", "version", "--", "--debug"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert calls["command"] == "vite"
    assert calls["cwd"] == project_root
    assert calls["argv"] == ["--version", "--debug"]


def test_run_unknown_command_lists_available_commands(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    code, _stdout, stderr = run_cli(["run", "missing"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "Available commands" in stderr
    assert "version" in stderr


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


def test_unknown_subcommand_exits_with_usage_error(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc:
        main(["not-a-command"])

    assert exc.value.code == 2
