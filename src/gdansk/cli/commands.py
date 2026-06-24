from __future__ import annotations

import shlex

import typer

from gdansk._project import discover_project
from gdansk.cli.core import ProjectDir, eprint

app = typer.Typer()


@app.command()
def commands(project: ProjectDir = None) -> None:
    discovered = discover_project(project=project)
    if not discovered.commands:
        eprint("No [gdansk.commands] entries configured.")
        raise SystemExit(1)

    width = max(len(name) for name in discovered.commands)
    for name, command in sorted(discovered.commands.items()):
        print(f"{name:<{width}}  {shlex.join(command)}")
