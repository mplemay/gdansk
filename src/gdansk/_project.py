from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProjectError(Exception):
    pass


@dataclass(slots=True, kw_only=True, frozen=True)
class GdanskProject:
    root: Path
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
        if "belgie" in document:
            return directory

    msg = f"Could not find pyproject.toml with a [belgie] table. Searched: {', '.join(searched)}"
    raise ProjectError(msg)


def load_project(root: Path) -> GdanskProject:
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.is_file():
        msg = f"No pyproject.toml found at {root}"
        raise ProjectError(msg)

    document = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    belgie = document.get("belgie")
    if not isinstance(belgie, dict):
        msg = f"No [belgie] configuration found in {pyproject_path}"
        raise ProjectError(msg)

    dependencies = belgie.get("dependencies")
    has_dependencies = isinstance(dependencies, dict) and bool(dependencies)

    scripts_table = belgie.get("scripts")
    scripts: dict[str, str] = {}
    if isinstance(scripts_table, dict):
        for name, command in scripts_table.items():
            if not isinstance(command, str):
                msg = f"[belgie.scripts] entry '{name}' must be a string shell command"
                raise ProjectError(msg)
            scripts[name] = command

    return GdanskProject(
        root=root.resolve(),
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


def _read_pyproject_document(root: Path) -> dict[str, Any]:
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.is_file():
        msg = f"No pyproject.toml found at {root}"
        raise ProjectError(msg)
    document = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        msg = f"Invalid pyproject.toml at {pyproject_path}"
        raise ProjectError(msg)
    return document


def _entry_point_packages(document: dict[str, Any]) -> list[str]:
    project = document.get("project")
    if not isinstance(project, dict):
        return []

    scripts = project.get("scripts")
    if not isinstance(scripts, dict):
        return []

    packages: list[str] = []
    for target in scripts.values():
        if not isinstance(target, str) or ":" not in target:
            continue
        module = target.split(":", 1)[0]
        package = module.split(".", 1)[0]
        if package and package not in packages:
            packages.append(package)
    return packages


def _src_views_candidates(root: Path) -> list[Path]:
    src = root / "src"
    if not src.is_dir():
        return []

    return [child / "views" for child in sorted(src.iterdir()) if child.is_dir() and (child / "views").is_dir()]


def infer_frontend_relative_path(root: Path) -> Path:
    document = _read_pyproject_document(root)
    packages = _entry_point_packages(document)

    if len(packages) == 1:
        return Path("src") / packages[0] / "views"

    if len(packages) > 1:
        joined = ", ".join(packages)
        msg = (
            f"Multiple [project.scripts] entry-point packages found ({joined}). "
            "Pass --frontend to select the frontend root."
        )
        raise ProjectError(msg)

    candidates = _src_views_candidates(root)
    if len(candidates) == 1:
        return candidates[0].relative_to(root)

    if len(candidates) > 1:
        joined = ", ".join(str(path.relative_to(root)) for path in candidates)
        msg = (
            f"Multiple src/*/views directories found ({joined}). "
            "Add a single [project.scripts] entry point or pass --frontend."
        )
        raise ProjectError(msg)

    msg = (
        "Could not infer frontend root. Expected src/<package>/views "
        "(via [project.scripts] or a single src/*/views directory). "
        "Run `gdansk init` or pass --frontend."
    )
    raise ProjectError(msg)


def resolve_frontend_path(
    project: GdanskProject,
    override: Path | None = None,
) -> Path:
    if override is not None:
        return override.resolve() if override.is_absolute() else (project.root / override).resolve()

    frontend = infer_frontend_relative_path(project.root)
    return (project.root / frontend).resolve()


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
