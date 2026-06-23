from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from belgie import Command, Runtime
from belgie.errors import BelgieRuntimeError

from gdansk._project import GdanskProject, discover_project
from gdansk.packages import create_environment

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

DEFAULT_HOST: Final[str] = "127.0.0.1"
DEFAULT_PORT: Final[int] = 13_714


def dev_command_argv(host: str, port: int) -> list[str]:
    return ["--host", host, "--port", str(port)]


def task_origin(host: str, port: int) -> str:
    return f"http://{host}:{port}"


@dataclass(slots=True)
class CommandProcess:
    task: asyncio.Task[None]

    @property
    def is_running(self) -> bool:
        return not self.task.done()

    async def wait(self) -> None:
        await self.task

    async def stop(self) -> None:
        if not self.task.done():
            self.task.cancel()
        with suppress(asyncio.CancelledError, BelgieRuntimeError):
            await self.task


async def run_command(
    project: GdanskProject,
    command: str,
    *,
    argv: Sequence[str] = (),
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    environment = create_environment(project, frozen=True)
    async with environment as active_environment:
        await active_environment.install()
        async with Runtime(env=active_environment) as runtime:
            await runtime(
                Command(
                    command,
                    cwd=cwd,
                    env=dict(env) if env is not None else None,
                ),
            )(*argv)


async def run_project_command(
    start: Path,
    command: str,
    *,
    argv: Sequence[str] = (),
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    project = discover_project(start=start)
    await run_command(project, command, argv=argv, cwd=cwd, env=env)


async def start_command(
    project: GdanskProject,
    command: str,
    *,
    argv: Sequence[str] = (),
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> CommandProcess:
    task = asyncio.create_task(
        run_command(project, command, argv=argv, cwd=cwd, env=env),
    )
    await asyncio.sleep(0)
    if task.done():
        await task
    return CommandProcess(task=task)


async def start_project_command(
    start: Path,
    command: str,
    *,
    argv: Sequence[str] = (),
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> CommandProcess:
    project = discover_project(start=start)
    return await start_command(project, command, argv=argv, cwd=cwd, env=env)
