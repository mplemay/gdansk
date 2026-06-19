from __future__ import annotations

import os
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING

from belgie import Environment

from gdansk._project import (
    GdanskProject,
    ProjectError,
    atomic_replace,
    project_from_document,
    set_dependency_in_document,
    set_dependency_value_in_document,
    temporary_lockfile,
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
    if not project.has_dependencies:
        msg = f"No [gdansk.dependencies] entries found in {project.root / 'pyproject.toml'}"
        raise ProjectError(msg)

    lockfile = project.lockfile_path
    if frozen and not lockfile.is_file():
        msg = f"Missing gdansk lockfile at {lockfile}; run `gdansk lock`"
        raise ProjectError(msg)

    with project_directory(project.root):
        return Environment(
            project.dependency_mapping,
            lockfile=lockfile if frozen else None,
        )


def lock_project(project: GdanskProject) -> EnvironmentInstallResult:
    with temporary_lockfile(project.root) as temporary:
        with create_environment(project, frozen=False) as environment:
            result = environment.lock(lockfile=temporary)
        atomic_replace(temporary, project.lockfile_path)
        return result


def add_dependency(
    project: GdanskProject,
    *,
    alias: str,
    specifier: str,
    dev: bool,
) -> EnvironmentInstallResult:
    document = deepcopy(project.pyproject)
    set_dependency_in_document(document, alias, specifier, dev=dev)
    updated_project = project_from_document(project.root, document)
    with temporary_lockfile(project.root) as temporary:
        with create_environment(updated_project, frozen=False) as environment:
            result = environment.lock(lockfile=temporary)
        write_pyproject_document(project.root, document)
        atomic_replace(temporary, updated_project.lockfile_path)
        return result


def update_project(
    project: GdanskProject,
    packages: Sequence[str] | None,
    *,
    latest: bool,
) -> EnvironmentUpdateResult:
    document = deepcopy(project.pyproject)
    with temporary_lockfile(project.root) as temporary:
        with create_environment(project, frozen=False) as environment:
            result = environment.update(packages, latest=latest, lockfile_only=True)
            temporary.write_bytes(Path(result.lockfile).read_bytes())

        for change in result.changes:
            dependency = project.dependency(change.name)
            if dependency is None:
                msg = f"Belgie updated unknown dependency alias '{change.name}'"
                raise ProjectError(msg)
            value = dependency.updated_value(change.updated)
            set_dependency_value_in_document(document, dependency.group, dependency.alias, value)

        write_pyproject_document(project.root, document)
        atomic_replace(temporary, project.lockfile_path)
        return result
