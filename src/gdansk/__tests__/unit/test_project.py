from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from gdansk.__tests__.conftest import write_frontend_tree, write_pyproject
from gdansk._project import (
    ProjectError,
    discover_project,
    infer_frontend_relative_path,
    load_project,
    resolve_frontend_path,
    validate_frontend_root,
)


def test_load_project_parses_dependencies_and_commands(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    write_pyproject(
        root,
        commands={"lint": ["oxlint", "--fix"]},
        dependencies={"vite": "8.0.14", "react": "^19"},
        dev_dependencies={"oxlint": "1.68.0"},
    )

    project = load_project(root)

    assert project.root == root.resolve()
    assert project.commands == {"lint": ("oxlint", "--fix")}
    assert project.dependency_mapping == {
        "vite": "8.0.14",
        "react": "^19",
        "oxlint": "1.68.0",
    }
    dependency = project.dependency("oxlint")
    assert dependency is not None
    assert dependency.group == "dev"


def test_rejects_duplicate_dependency_aliases(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        """
[gdansk.dependencies]
react = "^19"

[gdansk.dependencies.dev]
react = "^20"
""",
        encoding="utf-8",
    )

    with pytest.raises(ProjectError, match="Duplicate dependency alias"):
        load_project(root)


@pytest.mark.parametrize(
    "command",
    [
        'lint = "oxlint --fix"',
        "lint = []",
        'lint = ["oxlint", 1]',
    ],
)
def test_rejects_invalid_commands(tmp_path: Path, command: str):
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text(f"[gdansk.commands]\n{command}\n", encoding="utf-8")

    with pytest.raises(ProjectError, match="non-empty array of strings"):
        load_project(root)


def test_legacy_belgie_table_has_migration_error(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text('[belgie.dependencies]\nvite = "8"\n', encoding="utf-8")

    with pytest.raises(ProjectError, match=r"rename \[belgie\.dependencies\]"):
        load_project(root)


def test_discover_project_from_nested_directory(gdansk_project: tuple[Path, Path]):
    project_root, frontend_root = gdansk_project
    nested = frontend_root / "widgets" / "hello"

    assert discover_project(start=nested).root == project_root.resolve()


def test_discover_project_errors_when_missing(tmp_path: Path):
    with pytest.raises(ProjectError, match="Could not find pyproject.toml"):
        discover_project(start=tmp_path)


def test_discover_project_errors_without_gdansk_table(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "example"\n', encoding="utf-8")

    with pytest.raises(ProjectError, match="Could not find pyproject.toml"):
        discover_project(start=root)


def test_infer_from_project_scripts(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    write_pyproject(
        root,
        project_name="get-time",
        project_scripts={"main": "get_time.__main__:main"},
    )

    assert infer_frontend_relative_path(root) == Path("src/get_time/views")


def test_infer_from_single_src_views(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    write_pyproject(root, project_scripts={})
    write_frontend_tree(root / "src" / "foo", "views")

    assert infer_frontend_relative_path(root) == Path("src/foo/views")


def test_infer_errors_multiple_scripts_packages(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    write_pyproject(
        root,
        project_scripts={
            "one": "alpha.__main__:main",
            "two": "beta.__main__:main",
        },
    )

    with pytest.raises(ProjectError, match="Multiple \\[project.scripts\\]"):
        infer_frontend_relative_path(root)


def test_infer_errors_multiple_src_views(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    write_pyproject(root, project_scripts={})
    write_frontend_tree(root / "src" / "alpha", "views")
    write_frontend_tree(root / "src" / "beta", "views")

    with pytest.raises(ProjectError, match="Multiple src/\\*/views"):
        infer_frontend_relative_path(root)


def test_infer_errors_when_nothing_matches(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    write_pyproject(root, project_scripts={})

    with pytest.raises(ProjectError, match="Could not infer frontend root"):
        infer_frontend_relative_path(root)


def test_resolve_frontend_uses_inferred_path(gdansk_project: tuple[Path, Path]):
    project_root, frontend_root = gdansk_project
    project = load_project(project_root)

    assert resolve_frontend_path(project) == frontend_root.resolve()


def test_resolve_frontend_uses_override(gdansk_project: tuple[Path, Path]):
    project_root, _ = gdansk_project
    project = load_project(project_root)
    override = project_root / "custom"

    assert resolve_frontend_path(project, override) == override.resolve()


def test_validate_frontend_root_happy_path(gdansk_project: tuple[Path, Path]):
    _, frontend_root = gdansk_project

    validate_frontend_root(frontend_root)


def test_validate_frontend_root_errors_without_vite_config(tmp_path: Path):
    frontend_root = write_frontend_tree(tmp_path)
    (frontend_root / "vite.config.ts").unlink()

    with pytest.raises(ProjectError, match="vite.config.ts"):
        validate_frontend_root(frontend_root)


def test_validate_frontend_root_errors_without_widgets(tmp_path: Path):
    frontend_root = write_frontend_tree(tmp_path)

    shutil.rmtree(frontend_root / "widgets")

    with pytest.raises(ProjectError, match="widgets"):
        validate_frontend_root(frontend_root)


def test_discover_project_with_explicit_root(gdansk_project: tuple[Path, Path]):
    project_root, _ = gdansk_project

    project = discover_project(project=project_root)

    assert project.root == project_root.resolve()
