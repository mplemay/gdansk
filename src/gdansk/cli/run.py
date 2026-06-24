from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from gdansk._project import discover_project
from gdansk.cli.core import ProjectDir, require_command, runtime_errors, task_args_from_context

app = typer.Typer()


@app.command()
def run(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Command name from [gdansk.commands]")],
    project: ProjectDir = None,
    watch: Annotated[bool, typer.Option("--watch", help="Keep the command running until interrupted")] = False,
) -> None:
    import gdansk.cli

    discovered = discover_project(project=project)
    configured = require_command(discovered, name)
    command, *fixed_arguments = configured
    argv = [*fixed_arguments, *task_args_from_context(ctx)]
    with runtime_errors():
        if watch:
            asyncio.run(
                gdansk.cli._run_until_signal(
                    gdansk.cli.start_command(discovered, command, cwd=discovered.root, argv=argv),
                ),
            )
        else:
            asyncio.run(
                gdansk.cli.run_command(discovered, command, cwd=discovered.root, argv=argv),
            )
