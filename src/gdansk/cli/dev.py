from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from gdansk._project import discover_project
from gdansk.cli.shared import (
    FrontendDir,
    ProjectDir,
    resolve_frontend,
    run_until_signal,
    runtime_errors,
)
from gdansk.task import DEFAULT_HOST, DEFAULT_PORT
from gdansk.vite import Vite

app = typer.Typer()


@app.command()
def dev(
    ctx: typer.Context,  # noqa: ARG001
    project: ProjectDir = None,
    frontend: FrontendDir = None,
    host: Annotated[str, typer.Option("--host", help="Dev server host")] = DEFAULT_HOST,
    port: Annotated[int, typer.Option("--port", help="Dev server port")] = DEFAULT_PORT,
) -> None:
    discovered = discover_project(project=project)
    frontend_path = resolve_frontend(discovered, frontend)
    vite = Vite(frontend_path, host=host, port=port)
    with runtime_errors():
        asyncio.run(
            run_until_signal(
                vite.start_dev(),
            ),
        )
