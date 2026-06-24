from __future__ import annotations

import asyncio

import typer

from gdansk._project import discover_project
from gdansk.cli._errors import runtime_errors
from gdansk.cli._helpers import resolve_frontend
from gdansk.cli._options import FrontendDir, ProjectDir
from gdansk.cli._task_args import task_args_from_context

app = typer.Typer()


@app.command()
def build(
    ctx: typer.Context,
    project: ProjectDir = None,
    frontend: FrontendDir = None,
) -> None:
    import gdansk.cli

    discovered = discover_project(project=project)
    frontend_path = resolve_frontend(discovered, frontend)
    with runtime_errors():
        asyncio.run(
            gdansk.cli.run_command(
                discovered,
                "vite",
                cwd=frontend_path,
                argv=["build", *task_args_from_context(ctx)],
            ),
        )
