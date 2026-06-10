from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from gdansk._core import RunTaskOptions, TaskProcess, TaskRunner

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

type PathType = str | PathLike[str]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 13_714


class DevStartParams(NamedTuple):
    argv: list[str]
    host: str
    port: int


def dev_task_argv(host: str, port: int) -> list[str]:
    return ["--host", host, "--port", str(port)]


def task_origin(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def dev_start_kwargs(
    host: str,
    port: int,
    argv: Sequence[str] = (),
) -> DevStartParams:
    return DevStartParams(
        argv=dev_task_argv(host, port) + list(argv),
        host=host,
        port=port,
    )


def build_run_task_options(  # noqa: PLR0913
    task_cwd: PathType,
    script: str,
    *,
    argv: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
    host: str | None = None,
    port: int | None = None,
) -> RunTaskOptions:
    return RunTaskOptions(
        str(Path(task_cwd)),
        script,
        argv=list(argv),
        env=dict(env or {}),
        host=host,
        port=port,
    )


async def run_task(
    task_cwd: PathType,
    script: str,
    *,
    argv: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
) -> None:
    options = build_run_task_options(task_cwd, script, argv=argv, env=env)
    await TaskRunner().run(options)


async def start_task(  # noqa: PLR0913
    task_cwd: PathType,
    script: str,
    *,
    argv: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
    host: str | None = None,
    port: int | None = None,
) -> TaskProcess:
    options = build_run_task_options(
        task_cwd,
        script,
        argv=argv,
        env=env,
        host=host,
        port=port,
    )
    return await TaskRunner().start(options)
