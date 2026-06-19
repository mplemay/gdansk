from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

from belgie import Environment

from gdansk._project import (
    GdanskProject,
    ProjectError,
    _load_project_from_document,
    write_pyproject_document,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from belgie import EnvironmentInstallResult, EnvironmentUpdateResult


@contextmanager
def project_directory(root: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(root)
    try:
        yield
    finally:
        os.chdir(previous)


def create_environment(project: GdanskProject, *, frozen: bool) -> Environment:
    if not project.dependencies:
        msg = f"No [gdansk.dependencies] entries found in {project.root / 'pyproject.toml'}"
        raise ProjectError(msg)

    lockfile = project.root / "deno.lock"
    if frozen and not lockfile.is_file():
        msg = f"Missing gdansk lockfile at {lockfile}; run `gdansk lock`"
        raise ProjectError(msg)

    with project_directory(project.root):
        return Environment(
            project.dependency_mapping,
            lockfile=lockfile if frozen else None,
        )


def _temporary_path(root: Path, name: str) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{name}.", dir=root)
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    return temporary


def _commit_lockfile(source: Path, project: GdanskProject) -> Path:
    target = project.root / "deno.lock"
    source.replace(target)
    return target


def lock_project(project: GdanskProject) -> EnvironmentInstallResult:
    temporary = _temporary_path(project.root, "deno.lock")
    try:
        with create_environment(project, frozen=False) as environment:
            result = environment.lock(lockfile=temporary)
        _commit_lockfile(temporary, project)
        return result
    finally:
        temporary.unlink(missing_ok=True)


def add_dependency(
    project: GdanskProject,
    *,
    alias: str,
    specifier: str,
    dev: bool,
) -> EnvironmentInstallResult:
    if not alias.strip() or alias == "dev":
        msg = "Dependency alias must not be empty or use the reserved name 'dev'"
        raise ProjectError(msg)
    if not specifier.strip():
        msg = "Dependency specifier must not be empty"
        raise ProjectError(msg)

    document = deepcopy(project.pyproject)
    gdansk = document.setdefault("gdansk", {})
    if not isinstance(gdansk, dict):
        msg = "[gdansk] must be a table"
        raise ProjectError(msg)
    dependencies = gdansk.setdefault("dependencies", {})
    if not isinstance(dependencies, dict):
        msg = "[gdansk.dependencies] must be a table"
        raise ProjectError(msg)
    dev_dependencies = dependencies.setdefault("dev", {})
    if not isinstance(dev_dependencies, dict):
        msg = "[gdansk.dependencies.dev] must be a table"
        raise ProjectError(msg)

    dependencies.pop(alias, None)
    dev_dependencies.pop(alias, None)
    target = dev_dependencies if dev else dependencies
    target[alias] = specifier

    updated_project = _load_project_from_document(project.root, document)
    temporary = _temporary_path(project.root, "deno.lock")
    try:
        with create_environment(updated_project, frozen=False) as environment:
            result = environment.lock(lockfile=temporary)
        write_pyproject_document(project.root, document)
        _commit_lockfile(temporary, updated_project)
        return result
    finally:
        temporary.unlink(missing_ok=True)


def update_project(
    project: GdanskProject,
    packages: Sequence[str] | None,
    *,
    latest: bool,
) -> EnvironmentUpdateResult:
    document = deepcopy(project.pyproject)
    temporary = _temporary_path(project.root, "deno.lock")
    try:
        with create_environment(project, frozen=False) as environment:
            result = environment.update(packages, latest=latest, lockfile_only=True)
            temporary.write_bytes(Path(result.lockfile).read_bytes())

        for change in result.changes:
            dependency = project.dependency(change.name)
            if dependency is None:
                msg = f"Belgie updated unknown dependency alias '{change.name}'"
                raise ProjectError(msg)
            value = dependency.updated_value(change.updated)
            _set_dependency_value(document, dependency.group, dependency.alias, value)

        write_pyproject_document(project.root, document)
        _commit_lockfile(temporary, project)
        return result
    finally:
        temporary.unlink(missing_ok=True)


def _set_dependency_value(document: dict[str, Any], group: str, alias: str, value: str) -> None:
    gdansk = document["gdansk"]
    dependencies = gdansk["dependencies"]
    if group == "default":
        dependencies[alias] = value
    else:
        dependencies[group][alias] = value
