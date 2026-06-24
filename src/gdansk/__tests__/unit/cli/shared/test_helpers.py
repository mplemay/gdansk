from __future__ import annotations

from pathlib import Path

import pytest

from gdansk._project import Dependency, GdanskProject, ProjectError, load_project
from gdansk.cli.shared.helpers import require_command, resolve_frontend


def _project(
    root: Path,
    *,
    commands: dict[str, tuple[str, ...]] | None = None,
    dependencies: tuple[Dependency, ...] = (),
) -> GdanskProject:
    return GdanskProject(
        root=root,
        commands=commands or {},
        dependencies=dependencies,
        dependencies_by_alias={dependency.alias: dependency for dependency in dependencies},
        pyproject={},
    )


def test_require_command_returns_configured_argv():
    project = _project(Path("/project"), commands={"version": ("vite", "--version")})
    assert require_command(project, "version") == ("vite", "--version")


def test_require_command_missing_without_other_commands(capsys: pytest.CaptureFixture[str]):
    project = _project(Path("/project"))

    with pytest.raises(SystemExit) as exc:
        require_command(project, "missing")

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "No [gdansk.commands] entry 'missing'" in captured.err
    assert "Available commands" not in captured.err


def test_require_command_missing_lists_available_commands(capsys: pytest.CaptureFixture[str]):
    project = _project(
        Path("/project"),
        commands={
            "version": ("vite", "--version"),
            "build": ("vite", "build"),
        },
    )

    with pytest.raises(SystemExit) as exc:
        require_command(project, "missing")

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Available commands" in captured.err
    assert "build" in captured.err
    assert "version" in captured.err


def test_resolve_frontend_uses_project_layout(gdansk_project: tuple[Path, Path]):
    project_root, frontend = gdansk_project
    project = load_project(project_root)
    assert resolve_frontend(project, None) == frontend


def test_resolve_frontend_override(gdansk_project: tuple[Path, Path]):
    project_root, frontend = gdansk_project
    project = load_project(project_root)
    assert resolve_frontend(project, frontend) == frontend


def test_resolve_frontend_missing_path_raises():
    project = _project(Path("/project"))
    with pytest.raises(ProjectError, match="Frontend root does not exist"):
        resolve_frontend(project, Path("/project/missing-views"))
