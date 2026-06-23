from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self

import pytest
from belgie.errors import BelgieRuntimeError

from gdansk.__tests__.conftest import write_pyproject
from gdansk._project import ProjectError, load_project
from gdansk.task import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    CommandProcess,
    dev_command_argv,
    run_command,
    start_command,
    task_origin,
)

type CommandRunner = Callable[..., Awaitable[None]]


class FakeAsyncEnvironment:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def install(self) -> None:
        return None


class FakeRuntime:
    def __init__(self, *, env: object) -> None:
        self.env = env
        self.argv: tuple[str, ...] = ()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def __call__(self, _command: object) -> CommandRunner:
        async def runner(*argv: str) -> None:
            self.argv = argv

        return runner


class LifecycleTracker:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.command_calls: list[dict[str, Any]] = []
        self.captured_runtime: list[TrackingRuntime] = []

    def tracking_environment(self) -> TrackingEnvironment:
        return TrackingEnvironment(self)

    def tracking_runtime(self, *, env: object) -> TrackingRuntime:
        runtime = TrackingRuntime(self, env=env)
        self.captured_runtime.append(runtime)
        return runtime

    def fake_command(self, name: str, *, cwd: Path | None = None, env: dict[str, str] | None = None) -> SimpleNamespace:
        self.events.append("command")
        call = {"name": name, "cwd": cwd, "env": env}
        self.command_calls.append(call)
        return SimpleNamespace(**call)


class TrackingEnvironment:
    def __init__(self, tracker: LifecycleTracker) -> None:
        self._tracker = tracker

    async def __aenter__(self) -> Self:
        self._tracker.events.append("env_enter")
        return self

    async def __aexit__(self, *_args: object) -> None:
        self._tracker.events.append("env_exit")

    async def install(self) -> None:
        self._tracker.events.append("install")


class TrackingRuntime:
    def __init__(self, tracker: LifecycleTracker, *, env: object) -> None:
        self._tracker = tracker
        self.env = env
        self.argv: tuple[str, ...] = ()

    async def __aenter__(self) -> Self:
        self._tracker.events.append("runtime_enter")
        return self

    async def __aexit__(self, *_args: object) -> None:
        self._tracker.events.append("runtime_exit")

    def __call__(self, _command: object) -> CommandRunner:
        async def runner(*argv: str) -> None:
            self._tracker.events.append("command_invoke")
            self.argv = argv

        return runner


def test_dev_command_argv_formats_host_and_port():
    assert dev_command_argv(DEFAULT_HOST, DEFAULT_PORT) == [
        "--host",
        DEFAULT_HOST,
        "--port",
        str(DEFAULT_PORT),
    ]


def test_task_origin_builds_http_url():
    assert task_origin(DEFAULT_HOST, DEFAULT_PORT) == f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"


async def test_run_command_enters_environment_installs_before_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_pyproject(tmp_path)
    project = load_project(tmp_path)
    tracker = LifecycleTracker()
    fake_environment = tracker.tracking_environment()

    def fake_create_environment(_project: object, *, frozen: bool) -> TrackingEnvironment:
        assert frozen is True
        return fake_environment

    monkeypatch.setattr("gdansk.task.create_environment", fake_create_environment)
    monkeypatch.setattr("gdansk.task.Command", tracker.fake_command)
    monkeypatch.setattr("gdansk.task.Runtime", tracker.tracking_runtime)

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    await run_command(
        project,
        "vite",
        argv=["build", "--minify"],
        cwd=frontend,
        env={"NODE_ENV": "production"},
    )

    assert tracker.events == [
        "env_enter",
        "install",
        "runtime_enter",
        "command",
        "command_invoke",
        "runtime_exit",
        "env_exit",
    ]
    runtime = tracker.captured_runtime[-1]
    assert runtime.env is fake_environment
    assert runtime.argv == ("build", "--minify")
    assert tracker.command_calls == [
        {"name": "vite", "cwd": frontend, "env": {"NODE_ENV": "production"}},
    ]


async def test_run_command_forwards_argv_as_separate_args(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_pyproject(tmp_path)
    project = load_project(tmp_path)
    captured_runtime: list[FakeRuntime] = []

    def fake_runtime(*, env: object) -> FakeRuntime:
        runtime = FakeRuntime(env=env)
        captured_runtime.append(runtime)
        return runtime

    monkeypatch.setattr("gdansk.task.create_environment", lambda *_args, **_kwargs: FakeAsyncEnvironment())
    monkeypatch.setattr("gdansk.task.Command", lambda name, **kwargs: SimpleNamespace(name=name, **kwargs))
    monkeypatch.setattr("gdansk.task.Runtime", fake_runtime)

    await run_command(project, "vite", argv=["--version"])

    runtime = captured_runtime[-1]
    assert runtime.argv == ("--version",)


async def test_start_command_surfaces_immediate_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_pyproject(tmp_path)
    project = load_project(tmp_path)

    async def failing_run_command(*_args: object, **_kwargs: object) -> None:
        msg = "lockfile missing"
        raise ProjectError(msg)

    monkeypatch.setattr("gdansk.task.run_command", failing_run_command)

    with pytest.raises(ProjectError, match="lockfile missing"):
        await start_command(project, "vite")


async def test_command_process_stop_cancels_without_leaking_runtime_error():
    async def long_running_command() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            msg = "command interrupted"
            raise BelgieRuntimeError(msg) from None

    task = asyncio.create_task(long_running_command())
    process = CommandProcess(task=task)
    await process.stop()


async def test_command_process_stop_cancels_task():
    async def wait_forever() -> None:
        await asyncio.Event().wait()

    task = asyncio.create_task(wait_forever())
    process = CommandProcess(task=task)
    await process.stop()
    assert task.cancelled() is True
