from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from gdansk import GdanskRuntimeError
from gdansk.cli import main


def _run_main(
    argv: list[str],
    *,
    monkeypatch: pytest.MonkeyPatch,
    cwd: Path,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    monkeypatch.chdir(cwd)
    exit_code = 0
    try:
        main(argv)
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 0
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_version_prints_package_version(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "gdansk" in captured.out


def test_help_lists_subcommands(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc:
        main(["install", "--help"])

    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "install" in captured.out
    assert "--project" in captured.out


def test_install_dispatches_to_install_packages(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    def fake_install_packages(**kwargs: Any) -> SimpleNamespace:
        calls.update(kwargs)
        return SimpleNamespace(lockfile=str(project_root / "deno.lock"), dependencies=2, dev_dependencies=1)

    monkeypatch.setattr("gdansk.cli.install_packages", fake_install_packages)

    code, stdout, _stderr = _run_main(["install"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert calls["cwd"] == project_root
    assert calls["include_dev"] is True
    assert calls["lockfile_only"] is False
    assert "Installed 2 dependencies (+1 dev)" in stdout


def test_install_no_dev_flag(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    def fake_install_packages(**kwargs: Any) -> SimpleNamespace:
        calls.update(kwargs)
        return SimpleNamespace(lockfile=str(project_root / "deno.lock"), dependencies=1, dev_dependencies=0)

    monkeypatch.setattr("gdansk.cli.install_packages", fake_install_packages)

    _run_main(["install", "--no-dev"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert calls["include_dev"] is False


def test_lock_dispatches_to_lock_packages(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    def fake_lock_packages(**kwargs: Any) -> SimpleNamespace:
        calls.update(kwargs)
        return SimpleNamespace(lockfile=str(project_root / "deno.lock"), dependencies=1, dev_dependencies=0)

    monkeypatch.setattr("gdansk.cli.lock_packages", fake_lock_packages)

    _run_main(["lock"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert calls["cwd"] == project_root


def test_update_dispatches_packages_and_latest(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    def fake_update_packages(**kwargs: Any) -> SimpleNamespace:
        calls.update(kwargs)
        return SimpleNamespace(
            lockfile=str(project_root / "deno.lock"),
            changes=[SimpleNamespace(name="vite", previous="8.0.0", updated="8.0.14")],
        )

    monkeypatch.setattr("gdansk.cli.update_packages", fake_update_packages)

    _run_main(
        ["update", "vite", "react", "--latest"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert calls["packages"] == ["vite", "react"]
    assert calls["latest"] is True


def test_install_maps_runtime_error_to_exit_1(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    def fake_install_packages(**_kwargs: Any) -> SimpleNamespace:
        msg = "install failed"
        raise GdanskRuntimeError(msg)

    monkeypatch.setattr("gdansk.cli.install_packages", fake_install_packages)

    code, _stdout, stderr = _run_main(["install"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "install failed" in stderr


def test_build_dispatches_run_task(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    def fake_run_task_command(_args: Any, *, script: str, long_running: bool) -> None:
        calls["script"] = script
        calls["long_running"] = long_running
        calls["task_args"] = list(_args.task_args)

    monkeypatch.setattr("gdansk.cli._run_task_command", fake_run_task_command)

    _run_main(["build"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert calls["script"] == "build"
    assert calls["long_running"] is False
    assert calls["task_args"] == []


def test_build_forwards_task_args(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    def fake_run_task_command(args: Any, *, script: str, long_running: bool) -> None:
        calls["task_args"] = list(args.task_args)

    monkeypatch.setattr("gdansk.cli._run_task_command", fake_run_task_command)

    _run_main(["build", "--", "--outDir", "dist"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert calls["task_args"] == ["--outDir", "dist"]


def test_dev_dispatches_start_task(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    def fake_run_task_command(args: Any, *, script: str, long_running: bool) -> None:
        calls["script"] = script
        calls["long_running"] = long_running
        calls["host"] = args.host
        calls["port"] = args.port

    monkeypatch.setattr("gdansk.cli._run_task_command", fake_run_task_command)

    _run_main(["dev"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert calls["script"] == "dev"
    assert calls["long_running"] is True
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 13714


def test_run_unknown_script_suggests_scripts(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    code, _stdout, stderr = _run_main(["run", "missing"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 1
    assert "Available scripts" in stderr


def test_run_build_uses_run_task(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    def fake_run_task_command(_args: Any, *, script: str, long_running: bool) -> None:
        calls["script"] = script
        calls["long_running"] = long_running

    monkeypatch.setattr("gdansk.cli._run_task_command", fake_run_task_command)

    _run_main(["run", "build"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert calls["script"] == "build"
    assert calls["long_running"] is False


def test_run_dev_uses_start_task(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    calls: dict[str, Any] = {}

    def fake_run_task_command(_args: Any, *, script: str, long_running: bool) -> None:
        calls["script"] = script
        calls["long_running"] = long_running

    monkeypatch.setattr("gdansk.cli._run_task_command", fake_run_task_command)

    _run_main(["run", "dev"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert calls["script"] == "dev"
    assert calls["long_running"] is True


def test_run_watch_does_not_pass_dev_host_port(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project
    captured: dict[str, object] = {}

    class FakeTaskProcess:
        origin = ""
        is_running = True

        async def stop(self) -> None:
            return None

    async def fake_start_task(
        task_cwd: Path,
        script: str,
        **kwargs: object,
    ) -> FakeTaskProcess:
        captured["task_cwd"] = task_cwd
        captured["script"] = script
        captured.update(kwargs)
        return FakeTaskProcess()

    async def fake_run_until_signal(coro: Awaitable[FakeTaskProcess]) -> None:
        process = await coro
        await process.stop()

    def fake_asyncio_run(coro: Awaitable[FakeTaskProcess]) -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()

    monkeypatch.setattr("gdansk.cli.start_task", fake_start_task)
    monkeypatch.setattr("gdansk.cli._run_until_signal", fake_run_until_signal)
    monkeypatch.setattr("gdansk.cli.asyncio.run", fake_asyncio_run)

    _run_main(
        ["run", "build", "--watch"],
        monkeypatch=monkeypatch,
        cwd=project_root,
        capsys=capsys,
    )

    assert captured["script"] == "build"
    assert captured.get("host") is None
    assert captured.get("port") is None


def test_scripts_lists_entries(
    gdansk_project: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root, _ = gdansk_project

    code, stdout, _stderr = _run_main(["scripts"], monkeypatch=monkeypatch, cwd=project_root, capsys=capsys)

    assert code == 0
    assert "build" in stdout
    assert "vite build" in stdout
    assert "dev" in stdout


def test_unknown_subcommand_exits_with_argparse_error(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc:
        main(["not-a-command"])

    assert exc.value.code == 2
