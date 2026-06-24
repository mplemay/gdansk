from __future__ import annotations

from typing import Annotated

import typer

from gdansk._project import discover_project
from gdansk.cli.shared import ProjectDir, runtime_errors

app = typer.Typer()


@app.command()
def add(
    alias: Annotated[str, typer.Argument(help="JavaScript import alias")],
    specifier: Annotated[str, typer.Argument(help="npm version requirement or full npm:/jsr: specifier")],
    project: ProjectDir = None,
    dev: Annotated[bool, typer.Option("--dev", help="Add to [gdansk.dependencies.dev]")] = False,
) -> None:
    import gdansk.cli

    discovered = discover_project(project=project)
    with runtime_errors():
        gdansk.cli.add_dependency(
            discovered,
            alias=alias,
            specifier=specifier,
            dev=dev,
        )
    group = "dev" if dev else "default"
    print(f"Added {alias} to {group} dependencies. Lockfile: {discovered.lockfile_path}")
