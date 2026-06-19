from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import rtoml


class ProjectError(Exception):
    pass


@dataclass(slots=True, kw_only=True, frozen=True)
class Dependency:
    alias: str
    group: str
    specifier: str

    @property
    def is_full_specifier(self) -> bool:
        return self.specifier.startswith(("npm:", "jsr:"))

    def updated_value(self, specifier: str) -> str:
        if self.is_full_specifier:
            return specifier

        prefix = f"npm:{self.alias}@"
        if not specifier.startswith(prefix):
            msg = f"Updated dependency '{self.alias}' no longer resolves to its npm package: {specifier}"
            raise ProjectError(msg)
        return specifier.removeprefix(prefix)


@dataclass(slots=True, kw_only=True, frozen=True)
class GdanskProject:
    root: Path
    commands: dict[str, tuple[str, ...]]
    dependencies: tuple[Dependency, ...]
    pyproject: dict[str, Any]

    @property
    def dependency_mapping(self) -> dict[str, str]:
        return {dependency.alias: dependency.specifier for dependency in self.dependencies}

    @property
    def has_dependencies(self) -> bool:
        return bool(self.dependencies)

    def dependency(self, alias: str) -> Dependency | None:
        return next((dependency for dependency in self.dependencies if dependency.alias == alias), None)


def read_pyproject_document(root: Path) -> dict[str, Any]:
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.is_file():
        msg = f"No pyproject.toml found at {root}"
        raise ProjectError(msg)
    try:
        document = rtoml.load(pyproject_path)
    except Exception as error:
        msg = f"Invalid pyproject.toml at {pyproject_path}: {error}"
        raise ProjectError(msg) from error
    if not isinstance(document, dict):
        msg = f"Invalid pyproject.toml at {pyproject_path}"
        raise ProjectError(msg)
    return document


def write_pyproject_document(root: Path, document: dict[str, Any]) -> None:
    path = root / "pyproject.toml"
    text = rtoml.dumps(document, pretty=True)
    atomic_write_text(path, text)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(text)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _gdansk_table(document: dict[str, Any]) -> dict[str, Any] | None:
    gdansk = document.get("gdansk")
    if isinstance(gdansk, dict):
        return gdansk
    return None


def _legacy_belgie_error(root: Path) -> ProjectError:
    return ProjectError(
        f"Unsupported [belgie] configuration in {root / 'pyproject.toml'}; "
        "rename [belgie.dependencies] to [gdansk.dependencies] and "
        "[belgie.scripts] to array-based [gdansk.commands]",
    )


def _parse_dependencies(gdansk: dict[str, Any]) -> tuple[Dependency, ...]:
    table = gdansk.get("dependencies")
    if table is None:
        return ()
    if not isinstance(table, dict):
        msg = "[gdansk.dependencies] must be a table"
        raise ProjectError(msg)

    dependencies: list[Dependency] = []
    aliases: set[str] = set()
    for alias, value in table.items():
        if alias == "dev" and isinstance(value, dict):
            for dev_alias, dev_value in value.items():
                _append_dependency(dependencies, aliases, dev_alias, dev_value, group="dev")
            continue
        if isinstance(value, dict):
            msg = f"Unsupported dependency group [gdansk.dependencies.{alias}]; only .dev is supported"
            raise ProjectError(msg)
        _append_dependency(dependencies, aliases, alias, value, group="default")
    return tuple(dependencies)


def _append_dependency(
    dependencies: list[Dependency],
    aliases: set[str],
    alias: object,
    value: object,
    *,
    group: str,
) -> None:
    if (
        not isinstance(alias, str)
        or not alias.strip()
        or alias == "dev"
        or not isinstance(value, str)
        or not value.strip()
    ):
        msg = f"[gdansk.dependencies{'.dev' if group == 'dev' else ''}] entries must map strings to strings"
        raise ProjectError(msg)
    if alias in aliases:
        msg = f"Duplicate dependency alias '{alias}' across [gdansk.dependencies] groups"
        raise ProjectError(msg)
    aliases.add(alias)
    dependencies.append(Dependency(alias=alias, group=group, specifier=value))


def _parse_commands(gdansk: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    table = gdansk.get("commands")
    if table is None:
        return {}
    if not isinstance(table, dict):
        msg = "[gdansk.commands] must be a table"
        raise ProjectError(msg)

    commands: dict[str, tuple[str, ...]] = {}
    for name, value in table.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(value, list) or not value:
            msg = f"[gdansk.commands] entry '{name}' must be a non-empty array of strings"
            raise ProjectError(msg)
        if not all(isinstance(item, str) and item for item in value):
            msg = f"[gdansk.commands] entry '{name}' must be a non-empty array of strings"
            raise ProjectError(msg)
        commands[name] = tuple(value)
    return commands


def _load_project_from_document(root: Path, document: dict[str, Any]) -> GdanskProject:
    if isinstance(document.get("belgie"), dict):
        raise _legacy_belgie_error(root)

    gdansk = _gdansk_table(document)
    if gdansk is None:
        msg = f"No [gdansk] configuration found in {root / 'pyproject.toml'}"
        raise ProjectError(msg)

    return GdanskProject(
        root=root.resolve(),
        commands=_parse_commands(gdansk),
        dependencies=_parse_dependencies(gdansk),
        pyproject=document,
    )


def _find_project_with_document(start: Path | None = None) -> tuple[Path, dict[str, Any]]:
    start_path = (start or Path.cwd()).resolve()
    searched: list[str] = []

    for directory in (start_path, *start_path.parents):
        pyproject_path = directory / "pyproject.toml"
        searched.append(str(pyproject_path))
        if not pyproject_path.is_file():
            continue

        document = read_pyproject_document(directory)
        if isinstance(document.get("belgie"), dict):
            raise _legacy_belgie_error(directory)
        if _gdansk_table(document) is not None:
            return directory, document

    msg = f"Could not find pyproject.toml with a [gdansk] table. Searched: {', '.join(searched)}"
    raise ProjectError(msg)


def find_project_root(start: Path | None = None) -> Path:
    root, _ = _find_project_with_document(start)
    return root


def load_project(root: Path) -> GdanskProject:
    return _load_project_from_document(root, read_pyproject_document(root))


def discover_project(
    *,
    project: Path | None = None,
    start: Path | None = None,
) -> GdanskProject:
    if project is not None:
        return load_project(project.resolve())
    root, document = _find_project_with_document(start)
    return _load_project_from_document(root, document)


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


def infer_frontend_relative_path(root: Path, *, document: dict[str, Any] | None = None) -> Path:
    doc = document if document is not None else read_pyproject_document(root)
    packages = _entry_point_packages(doc)

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

    frontend = infer_frontend_relative_path(project.root, document=project.pyproject)
    return (project.root / frontend).resolve()


def validate_frontend_root(path: Path) -> None:
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
