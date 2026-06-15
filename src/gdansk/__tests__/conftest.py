from __future__ import annotations

from json import dumps
from typing import TYPE_CHECKING

import pytest

from gdansk.cli import main

if TYPE_CHECKING:
    from pathlib import Path


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
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 0
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def write_pyproject(
    root: Path,
    *,
    scripts: dict[str, str] | None = None,
    dependencies: dict[str, str] | None = None,
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

    deps = dependencies if dependencies is not None else {"vite": "8.0.8"}
    if deps:
        lines.append("[belgie.dependencies]")
        lines.extend(f"{dumps(name)} = {dumps(value)}" for name, value in deps.items())
        lines.append("")

    script_map = scripts if scripts is not None else {"build": "vite build", "dev": "vite"}
    if script_map:
        lines.append("[belgie.scripts]")
        lines.extend(f"{dumps(name)} = {dumps(command)}" for name, command in script_map.items())
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
        "export default function App() { return null; }\n",
        encoding="utf-8",
    )
    (frontend / "vite.config.ts").write_text(
        "export default {};\n",
        encoding="utf-8",
    )
    return frontend


def write_src_layout_project(
    root: Path,
    *,
    package: str = "example",
    scripts: dict[str, str] | None = None,
    dependencies: dict[str, str] | None = None,
    project_name: str = "example",
) -> tuple[Path, Path]:
    write_pyproject(
        root,
        scripts=scripts,
        dependencies=dependencies,
        project_name=project_name,
        project_scripts={"main": f"{package}.__main__:main"},
    )
    frontend_root = write_frontend_tree(root / "src" / package, "views")
    return root, frontend_root


@pytest.fixture
def views_path(tmp_path: Path) -> Path:
    views = tmp_path / "views"
    (views / "widgets" / "hello").mkdir(parents=True)
    (views / "widgets" / "hello" / "widget.tsx").write_text(
        "export default function App() { return null; }\n",
        encoding="utf-8",
    )
    (views / "dist").mkdir(parents=True, exist_ok=True)
    return views


@pytest.fixture
def gdansk_project(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    return write_src_layout_project(project_root)
