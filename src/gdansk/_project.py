from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import rtoml

if TYPE_CHECKING:
    from collections.abc import Iterator

LOCKFILE_NAME: Final[str] = "deno.lock"
DEFAULT_GROUP: Final[str] = "default"
DEV_GROUP: Final[str] = "dev"


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
    dependencies_by_alias: dict[str, Dependency]
    pyproject: dict[str, Any]

    @property
    def dependency_mapping(self) -> dict[str, str]:
        return {alias: dependency.specifier for alias, dependency in self.dependencies_by_alias.items()}

    @property
    def has_dependencies(self) -> bool:
        return bool(self.dependencies)

    @property
    def lockfile_path(self) -> Path:
        return self.root / LOCKFILE_NAME

    def dependency(self, alias: str) -> Dependency | None:
        return self.dependencies_by_alias.get(alias)


def _temporary_file(parent: Path, prefix: str) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(prefix=prefix, dir=parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    return temporary


@contextmanager
def temporary_lockfile(root: Path) -> Iterator[Path]:
    temporary = _temporary_file(root, f".{LOCKFILE_NAME}.")
    try:
        yield temporary
    finally:
        temporary.unlink(missing_ok=True)


def read_pyproject_document(root: Path) -> dict[str, Any]:
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.is_file():
        msg = f"No pyproject.toml found at {root}"
        raise ProjectError(msg)
    try:
        document = rtoml.load(pyproject_path)
    except (OSError, UnicodeDecodeError, rtoml.TomlParsingError) as exc:
        msg = f"Invalid pyproject.toml at {pyproject_path}: {exc}"
        raise ProjectError(msg) from exc
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
    temporary = _temporary_file(path.parent, f".{path.name}.")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def _gdansk_table(document: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(gdansk := document.get("gdansk"), dict):
        return gdansk
    return None


def _legacy_belgie_error(root: Path) -> ProjectError:
    return ProjectError(
        f"Unsupported [belgie] configuration in {root / 'pyproject.toml'}; "
        "rename [belgie.dependencies] to [gdansk.dependencies] and "
        "[belgie.scripts] to array-based [gdansk.commands]",
    )


def _ensure_dependencies_tables(document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(gdansk := document.setdefault("gdansk", {}), dict):
        msg = "[gdansk] must be a table"
        raise ProjectError(msg)
    if not isinstance(dependencies := gdansk.setdefault("dependencies", {}), dict):
        msg = "[gdansk.dependencies] must be a table"
        raise ProjectError(msg)
    if not isinstance(dev_dependencies := dependencies.setdefault("dev", {}), dict):
        msg = "[gdansk.dependencies.dev] must be a table"
        raise ProjectError(msg)
    return dependencies, dev_dependencies


def set_dependency_in_document(
    document: dict[str, Any],
    alias: str,
    specifier: str,
    *,
    dev: bool,
) -> None:
    if not alias.strip() or alias == DEV_GROUP:
        msg = "Dependency alias must not be empty or use the reserved name 'dev'"
        raise ProjectError(msg)
    if not specifier.strip():
        msg = "Dependency specifier must not be empty"
        raise ProjectError(msg)

    dependencies, dev_dependencies = _ensure_dependencies_tables(document)
    dependencies.pop(alias, None)
    dev_dependencies.pop(alias, None)
    target = dev_dependencies if dev else dependencies
    target[alias] = specifier


def set_dependency_value_in_document(
    document: dict[str, Any],
    group: str,
    alias: str,
    value: str,
) -> None:
    gdansk = document["gdansk"]
    dependencies = gdansk["dependencies"]
    if group == DEFAULT_GROUP:
        dependencies[alias] = value
    else:
        dependencies[group][alias] = value


def _parse_dependencies(gdansk: dict[str, Any]) -> tuple[Dependency, ...]:
    if (table := gdansk.get("dependencies")) is None:
        return ()
    if not isinstance(table, dict):
        msg = "[gdansk.dependencies] must be a table"
        raise ProjectError(msg)

    dependencies: list[Dependency] = []
    aliases: set[str] = set()
    for alias, value in table.items():
        if alias == DEV_GROUP and isinstance(value, dict):
            for dev_alias, dev_value in value.items():
                _append_dependency(dependencies, aliases, dev_alias, dev_value, group=DEV_GROUP)
            continue
        if isinstance(value, dict):
            msg = f"Unsupported dependency group [gdansk.dependencies.{alias}]; only .dev is supported"
            raise ProjectError(msg)
        _append_dependency(dependencies, aliases, alias, value, group=DEFAULT_GROUP)
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
        or alias == DEV_GROUP
        or not isinstance(value, str)
        or not value.strip()
    ):
        msg = f"[gdansk.dependencies{'.dev' if group == DEV_GROUP else ''}] entries must map strings to strings"
        raise ProjectError(msg)
    if alias in aliases:
        msg = f"Duplicate dependency alias '{alias}' across [gdansk.dependencies] groups"
        raise ProjectError(msg)
    aliases.add(alias)
    dependencies.append(Dependency(alias=alias, group=group, specifier=value))


def _parse_commands(gdansk: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    if (table := gdansk.get("commands")) is None:
        return {}
    if not isinstance(table, dict):
        msg = "[gdansk.commands] must be a table"
        raise ProjectError(msg)

    commands: dict[str, tuple[str, ...]] = {}
    for name, value in table.items():
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item for item in value)
        ):
            msg = f"[gdansk.commands] entry '{name}' must be a non-empty array of strings"
            raise ProjectError(msg)
        commands[name] = tuple(value)
    return commands


def _load_project_from_document(root: Path, document: dict[str, Any]) -> GdanskProject:
    if isinstance(document.get("belgie"), dict):
        raise _legacy_belgie_error(root)

    if (gdansk := _gdansk_table(document)) is None:
        msg = f"No [gdansk] configuration found in {root / 'pyproject.toml'}"
        raise ProjectError(msg)

    dependencies = _parse_dependencies(gdansk)
    return GdanskProject(
        root=root.resolve(),
        commands=_parse_commands(gdansk),
        dependencies=dependencies,
        dependencies_by_alias={dependency.alias: dependency for dependency in dependencies},
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
        if _gdansk_table(document) is not None:
            return directory, document

    msg = f"Could not find pyproject.toml with a [gdansk] table. Searched: {', '.join(searched)}"
    raise ProjectError(msg)


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
    if not isinstance(project := document.get("project"), dict):
        return []

    if not isinstance(scripts := project.get("scripts"), dict):
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

    if not (path / "widgets").is_dir():
        msg = f"Frontend root is missing widgets/: {path}"
        raise ProjectError(msg)
