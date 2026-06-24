from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from gdansk._project import discover_project
from gdansk.cli.core import (
    FrontendDir,
    ProjectDir,
    resolve_frontend,
    run_until_signal,
    runtime_errors,
    task_args_from_context,
)
from gdansk.task import DEFAULT_HOST, DEFAULT_PORT, dev_command_argv

app = typer.Typer()


@app.command()
def dev(
    ctx: typer.Context,
    project: ProjectDir = None,
    frontend: FrontendDir = None,
    host: Annotated[str, typer.Option("--host", help="Dev server host")] = DEFAULT_HOST,
    port: Annotated[int, typer.Option("--port", help="Dev server port")] = DEFAULT_PORT,
) -> None:
    import gdansk.cli

    discovered = discover_project(project=project)
    frontend_path = resolve_frontend(discovered, frontend)
    argv = [*dev_command_argv(host, port), *task_args_from_context(ctx)]
    with runtime_errors():
        asyncio.run(
            run_until_signal(
                gdansk.cli.start_command(discovered, "vite", cwd=frontend_path, argv=argv),
            ),
        )
