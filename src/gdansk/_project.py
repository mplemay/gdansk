from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


class ProjectError(Exception):
    pass


@dataclass(slots=True, kw_only=True, frozen=True)
class GdanskProject:
    root: Path
    frontend: Path | None
    scripts: dict[str, str]
    has_dependencies: bool


def find_project_root(start: Path | None = None) -> Path:
    start_path = (start or Path.cwd()).resolve()
    searched: list[str] = []

    for directory in (start_path, *start_path.parents):
        pyproject_path = directory / "pyproject.toml"
        searched.append(str(pyproject_path))
        if not pyproject_path.is_file():
            continue

        document = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        if "gdansk" in document:
            return directory

    msg = f"Could not find pyproject.toml with a [gdansk] table. Searched: {', '.join(searched)}"
    raise ProjectError(msg)


def load_project(root: Path) -> GdanskProject:
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.is_file():
        msg = f"No pyproject.toml found at {root}"
        raise ProjectError(msg)

    document = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    gdansk = document.get("gdansk")
    if not isinstance(gdansk, dict):
        msg = f"No [gdansk] configuration found in {pyproject_path}"
        raise ProjectError(msg)

    frontend_raw = gdansk.get("frontend")
    frontend: Path | None = None
    if isinstance(frontend_raw, str) and frontend_raw.strip():
        frontend = Path(frontend_raw)

    dependencies = gdansk.get("dependencies")
    has_dependencies = isinstance(dependencies, dict) and bool(dependencies)

    scripts_table = gdansk.get("scripts")
    scripts: dict[str, str] = {}
    if isinstance(scripts_table, dict):
        for name, command in scripts_table.items():
            if not isinstance(command, str):
                msg = f"[gdansk.scripts] entry '{name}' must be a string shell command"
                raise ProjectError(msg)
            scripts[name] = command

    return GdanskProject(
        root=root.resolve(),
        frontend=frontend,
        scripts=scripts,
        has_dependencies=has_dependencies,
    )


def discover_project(
    *,
    project: Path | None = None,
    start: Path | None = None,
) -> GdanskProject:
    root = project.resolve() if project is not None else find_project_root(start)
    return load_project(root)


def resolve_frontend_path(
    project: GdanskProject,
    override: Path | None = None,
) -> Path:
    if override is not None:
        return override.resolve() if override.is_absolute() else (project.root / override).resolve()

    if project.frontend is None:
        msg = (
            "No [gdansk] frontend path configured in pyproject.toml. "
            "Add a frontend setting under [gdansk] or pass --frontend."
        )
        raise ProjectError(msg)

    frontend = project.frontend
    return frontend.resolve() if frontend.is_absolute() else (project.root / frontend).resolve()


def validate_frontend_root(path: Path) -> list[str]:
    warnings: list[str] = []

    if not path.exists():
        msg = f"Frontend root does not exist: {path}"
        raise ProjectError(msg)

    if not path.is_dir():
        msg = f"Frontend root is not a directory: {path}"
        raise ProjectError(msg)

    if not (path / "vite.config.ts").is_file():
        msg = f"Frontend root is missing vite.config.ts: {path}"
        raise ProjectError(msg)

    widgets_dir = path / "widgets"
    if not widgets_dir.is_dir():
        msg = f"Frontend root is missing widgets/: {path}"
        raise ProjectError(msg)

    if not (path / "package.json").is_file():
        warnings.append(f"Frontend root is missing package.json: {path}")

    return warnings
