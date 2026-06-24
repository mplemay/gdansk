from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

import typer

from gdansk._project import GdanskProject, ProjectError, discover_project
from gdansk.cli.core import FrontendDir, ProjectDir, eprint, resolve_frontend

PYTHON_MIN: Final[tuple[int, int]] = (3, 12)
PYTHON_MAX: Final[tuple[int, int]] = (3, 15)

app = typer.Typer()


def _doctor_check_dependencies(project: GdanskProject, failures: list[str]) -> None:
    if project.has_dependencies:
        print(f"ok   [gdansk.dependencies] in {project.root / 'pyproject.toml'}")
        return

    message = "No [gdansk.dependencies] table found"
    print(f"fail {message}")
    failures.append(message)


def _doctor_check_frontend(
    project: GdanskProject,
    frontend: Path | None,
    failures: list[str],
    warnings: list[str],
) -> None:
    try:
        frontend_path = resolve_frontend(project, frontend)
    except ProjectError as exc:
        print(f"fail {exc}")
        failures.append(str(exc))
        return

    print(f"ok   frontend root ({frontend_path})")

    root_lock = project.lockfile_path
    if root_lock.is_file():
        print(f"ok   gdansk lockfile (deno.lock) at project root ({root_lock})")
    else:
        message = f"gdansk lockfile (deno.lock) missing at project root ({root_lock})"
        warnings.append(message)

    legacy_lock = frontend_path / "deno.lock"
    if legacy_lock.is_file() and not root_lock.is_file():
        message = f"Legacy lockfile found under frontend ({legacy_lock}); move it to the project root"
        warnings.append(message)


@app.command()
def doctor(
    project: ProjectDir = None,
    frontend: FrontendDir = None,
) -> None:
    failures: list[str] = []
    warnings: list[str] = []

    version = sys.version_info
    if version < PYTHON_MIN or version >= PYTHON_MAX:
        failures.append(
            f"Python {version.major}.{version.minor} (requires >={PYTHON_MIN[0]}.{PYTHON_MIN[1]},"
            f"<{PYTHON_MAX[0]}.{PYTHON_MAX[1]})",
        )
    else:
        print(f"ok   Python {version.major}.{version.minor}.{version.micro}")

    try:
        discovered = discover_project(project=project)
    except ProjectError as exc:
        print(f"fail {exc}")
        failures.append(str(exc))
    else:
        _doctor_check_dependencies(discovered, failures)
        _doctor_check_frontend(discovered, frontend, failures, warnings)

    for warning in warnings:
        eprint(f"warning: {warning}")

    if failures:
        eprint(f"doctor: {len(failures)} check(s) failed")
        raise SystemExit(1)

    if warnings:
        print(f"doctor: {len(warnings)} warning(s)")
    else:
        print("doctor: all checks passed")
