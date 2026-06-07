from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def write_pyproject(
    root: Path,
    *,
    frontend: str | None = "frontend",
    scripts: dict[str, str] | None = None,
    dependencies: dict[str, str] | None = None,
    include_project: bool = True,
) -> Path:
    lines: list[str] = []
    if include_project:
        lines.extend(
            [
                "[project]",
                'name = "example"',
                'version = "0.1.0"',
                "",
            ],
        )

    if frontend is not None:
        lines.extend(["[gdansk]", f'frontend = "{frontend}"', ""])

    deps = dependencies if dependencies is not None else {"vite": "8.0.14"}
    if deps:
        lines.append("[gdansk.dependencies]")
        lines.extend(f'{name} = "{value}"' for name, value in deps.items())
        lines.append("")

    script_map = scripts if scripts is not None else {"build": "vite build", "dev": "vite"}
    if script_map:
        lines.append("[gdansk.scripts]")
        lines.extend(f'{name} = "{command}"' for name, command in script_map.items())
        lines.append("")

    path = root / "pyproject.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_frontend_tree(
    root: Path,
    name: str = "frontend",
    *,
    include_package_json: bool = True,
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
    if include_package_json:
        (frontend / "package.json").write_text("{}\n", encoding="utf-8")
    return frontend


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
    write_pyproject(project_root)
    frontend_root = write_frontend_tree(project_root)
    return project_root, frontend_root
