from __future__ import annotations

import asyncio

import typer

from gdansk._project import discover_project
from gdansk.cli.shared import (
    FrontendDir,
    ProjectDir,
    resolve_frontend,
    runtime_errors,
)
from gdansk.vite import Vite

app = typer.Typer()


@app.command()
def build(
    ctx: typer.Context,  # noqa: ARG001
    project: ProjectDir = None,
    frontend: FrontendDir = None,
) -> None:
    discovered = discover_project(project=project)
    frontend_path = resolve_frontend(discovered, frontend)
    with runtime_errors():
        asyncio.run(
            Vite(frontend_path).build(),
        )
