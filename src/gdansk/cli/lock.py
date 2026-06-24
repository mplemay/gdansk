from __future__ import annotations

import typer

from gdansk._project import discover_project
from gdansk.cli.shared import ProjectDir, runtime_errors

app = typer.Typer()


@app.command()
def lock(project: ProjectDir = None) -> None:
    import gdansk.cli

    discovered = discover_project(project=project)
    with runtime_errors():
        result = gdansk.cli.lock_project(discovered)
    print(f"Locked {result.dependencies} dependencies. Lockfile: {discovered.lockfile_path}")
