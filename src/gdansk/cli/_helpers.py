from __future__ import annotations

import shlex
from pathlib import Path

from gdansk._project import GdanskProject, resolve_frontend_path, validate_frontend_root
from gdansk.cli._errors import eprint


def resolve_frontend(project: GdanskProject, frontend: Path | None) -> Path:
    frontend_path = resolve_frontend_path(project, frontend)
    validate_frontend_root(frontend_path)
    return frontend_path


def require_command(project: GdanskProject, name: str) -> tuple[str, ...]:
    if (command := project.commands.get(name)) is not None:
        return command

    eprint(f"No [gdansk.commands] entry '{name}' in {project.root / 'pyproject.toml'}")
    if project.commands:
        eprint("Available commands:")
        for command_name, command_argv in sorted(project.commands.items()):
            eprint(f"  {command_name}  {shlex.join(command_argv)}")
    raise SystemExit(1)
