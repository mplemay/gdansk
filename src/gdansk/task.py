from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING

from gdansk._core import RunTaskOptions, TaskProcess, TaskRunner

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

type PathType = str | PathLike[str]


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
