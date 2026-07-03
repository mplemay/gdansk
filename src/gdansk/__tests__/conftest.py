from __future__ import annotations

from json import dumps
from pathlib import Path

import pytest
import typer

from gdansk.cli import main

REPO_ROOT = Path(__file__).resolve().parents[3]


def run_cli(
    argv: list[str],
    *,
    monkeypatch: pytest.MonkeyPatch,
    cwd: Path,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    monkeypatch.chdir(cwd)
    exit_code = 0
    try:
        main(argv)
    except typer.Exit as exc:
        exit_code = exc.exit_code
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 0
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def stage_init_vite_package(init_target: Path) -> None:
    widget_dest = init_target.parent.parent / "packages" / "widget"
    widget_dest.parent.mkdir(parents=True, exist_ok=True)
    if not widget_dest.exists():
        widget_dest.symlink_to(REPO_ROOT / "packages" / "widget", target_is_directory=True)


def write_pyproject(
    root: Path,
    *,
    commands: dict[str, list[str]] | None = None,
    dependencies: dict[str, str] | None = None,
    dev_dependencies: dict[str, str] | None = None,
    include_project: bool = True,
    project_scripts: dict[str, str] | None = None,
    project_name: str = "example",
) -> Path:
    lines: list[str] = []
    if include_project:
        lines.extend(
            [
                "[project]",
                f'name = "{project_name}"',
                'version = "0.1.0"',
                "",
            ],
        )
        entry_scripts = project_scripts if project_scripts is not None else {"main": "example.__main__:main"}
        if entry_scripts:
            lines.append("[project.scripts]")
            lines.extend(f"{dumps(name)} = {dumps(target)}" for name, target in entry_scripts.items())
            lines.append("")

    deps = (
        dependencies
        if dependencies is not None
        else {
            "@gdansk/widget": f"file:{REPO_ROOT / 'packages' / 'widget'}",
            "react": "19.2.6",
            "react-dom": "19.2.6",
            "vite": "8.1.3",
        }
    )
    if deps:
        lines.append("[gdansk.dependencies]")
        lines.extend(f"{dumps(name)} = {dumps(value)}" for name, value in deps.items())
        lines.append("")

    dev_deps = dev_dependencies or {}
    if dev_deps:
        lines.append("[gdansk.dependencies.dev]")
        lines.extend(f"{dumps(name)} = {dumps(value)}" for name, value in dev_deps.items())
        lines.append("")

    command_map = commands if commands is not None else {"version": ["vite", "--version"]}
    if command_map:
        lines.append("[gdansk.commands]")
        lines.extend(f"{dumps(name)} = {dumps(command)}" for name, command in command_map.items())
        lines.append("")

    path = root / "pyproject.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_frontend_tree(
    root: Path,
    name: str = "frontend",
) -> Path:
    frontend = root / name
    (frontend / "widgets" / "hello").mkdir(parents=True, exist_ok=True)
    (frontend / "widgets" / "hello" / "widget.tsx").write_text(
        'import { render } from "@gdansk/widget";\n'
        "export default function widget() { return render({ widget: <main /> }); }\n",
        encoding="utf-8",
    )
    return frontend


def write_src_layout_project(
    root: Path,
    *,
    package: str = "example",
    commands: dict[str, list[str]] | None = None,
    dependencies: dict[str, str] | None = None,
    dev_dependencies: dict[str, str] | None = None,
    project_name: str = "example",
) -> tuple[Path, Path]:
    write_pyproject(
        root,
        commands=commands,
        dependencies=dependencies,
        dev_dependencies=dev_dependencies,
        project_name=project_name,
        project_scripts={"main": f"{package}.__main__:main"},
    )
    frontend_root = write_frontend_tree(root / "src" / package, "views")
    return root, frontend_root


@pytest.fixture
def views_path(tmp_path: Path) -> Path:
    views = write_frontend_tree(tmp_path, "views")
    (views / "dist").mkdir(parents=True, exist_ok=True)
    return views


@pytest.fixture
def gdansk_project(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    return write_src_layout_project(project_root)
