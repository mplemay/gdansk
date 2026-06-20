from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Self

import pytest

from gdansk.__tests__.conftest import write_pyproject
from gdansk._project import ProjectError, load_project, read_pyproject_document
from gdansk.packages import add_dependency, create_environment, lock_project, update_project


class FakeEnvironment:
    def __init__(
        self,
        *,
        lockfile: Path,
        changes: list[SimpleNamespace] | None = None,
    ) -> None:
        self.lockfile = lockfile
        self.changes = changes or []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def lock(self, *, lockfile: Path):
        lockfile.write_text('{"version":"5"}\n', encoding="utf-8")
        return SimpleNamespace(lockfile=str(lockfile), dependencies=3)

    def update(self, _packages, **_kwargs: bool):
        self.lockfile.write_text('{"version":"5"}\n', encoding="utf-8")
        return SimpleNamespace(lockfile=str(self.lockfile), changes=self.changes)


def test_create_environment_frozen_requires_lockfile(tmp_path: Path):
    write_pyproject(tmp_path)
    project = load_project(tmp_path)

    with pytest.raises(ProjectError, match=r"Missing gdansk lockfile"):
        create_environment(project, frozen=True)


def test_lock_project_writes_root_lockfile(tmp_path: Path, monkeypatch):
    write_pyproject(tmp_path)
    project = load_project(tmp_path)
    generated = tmp_path / "generated.lock"
    monkeypatch.setattr(
        "gdansk.packages.create_environment",
        lambda *_args, **_kwargs: FakeEnvironment(lockfile=generated),
    )

    result = lock_project(project)

    assert result.dependencies == 3
    assert (tmp_path / "deno.lock").read_text(encoding="utf-8") == '{"version":"5"}\n'


def test_add_dependency_moves_alias_to_dev_and_commits_after_lock(tmp_path: Path, monkeypatch):
    write_pyproject(tmp_path, dependencies={"react": "^19"})
    project = load_project(tmp_path)
    generated = tmp_path / "generated.lock"
    monkeypatch.setattr(
        "gdansk.packages.create_environment",
        lambda *_args, **_kwargs: FakeEnvironment(lockfile=generated),
    )

    add_dependency(project, alias="react", specifier="^20", dev=True)

    document = read_pyproject_document(tmp_path)
    assert "react" not in document["gdansk"]["dependencies"]
    assert document["gdansk"]["dependencies"]["dev"]["react"] == "^20"
    assert (tmp_path / "deno.lock").is_file()


def test_update_preserves_shorthand_and_full_specifier_style(tmp_path: Path, monkeypatch):
    write_pyproject(
        tmp_path,
        dependencies={
            "react": "^19",
            "std_path": "jsr:@std/path@^1",
        },
    )
    project = load_project(tmp_path)
    generated = tmp_path / "generated.lock"
    changes = [
        SimpleNamespace(name="react", previous="npm:react@^19", updated="npm:react@^20"),
        SimpleNamespace(
            name="std_path",
            previous="jsr:@std/path@^1",
            updated="jsr:@std/path@^2",
        ),
    ]
    monkeypatch.setattr(
        "gdansk.packages.create_environment",
        lambda *_args, **_kwargs: FakeEnvironment(lockfile=generated, changes=changes),
    )

    update_project(project, ["react", "std_path"], latest=True)

    document = read_pyproject_document(tmp_path)
    dependencies = document["gdansk"]["dependencies"]
    assert dependencies["react"] == "^20"
    assert dependencies["std_path"] == "jsr:@std/path@^2"
