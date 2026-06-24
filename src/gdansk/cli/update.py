from __future__ import annotations

from typing import Annotated

import typer

from gdansk._project import discover_project
from gdansk.cli.core.errors import runtime_errors
from gdansk.cli.core.options import ProjectDir

app = typer.Typer()


@app.command()
def update(
    packages: Annotated[list[str] | None, typer.Argument(help="Optional dependency aliases to update")] = None,
    project: ProjectDir = None,
    latest: Annotated[bool, typer.Option("--latest", help="Update to the latest versions")] = False,
) -> None:
    import gdansk.cli

    discovered = discover_project(project=project)
    with runtime_errors():
        result = gdansk.cli.update_project(discovered, packages or None, latest=latest)
    for change in result.changes:
        print(f"{change.name}: {change.previous} -> {change.updated}")
    print(f"Lockfile: {discovered.lockfile_path}")
