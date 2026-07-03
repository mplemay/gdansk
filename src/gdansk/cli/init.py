from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Annotated

import rtoml
import typer

from gdansk._project import (
    ProjectError,
    _gdansk_table,
    _legacy_belgie_error,
    atomic_write_text,
    load_project,
    read_pyproject_document,
    write_pyproject_document,
)
from gdansk.cli.shared import eprint, runtime_errors

app = typer.Typer()


def _normalize_package_name(name: str) -> str:
    return name.replace("-", "_")


def _template_text(name: str, *, package: str = "my_mcp_server") -> str:
    raw = resources.files("gdansk.cli.templates").joinpath(name).read_text(encoding="utf-8")
    return raw.replace("{{PACKAGE}}", package)


def _default_init_package(target_dir: Path) -> str:
    pyproject_path = target_dir / "pyproject.toml"
    if pyproject_path.is_file():
        document = read_pyproject_document(target_dir)
        if (
            isinstance(project := document.get("project"), dict)
            and isinstance(name := project.get("name"), str)
            and (stripped := name.strip())
        ):
            return _normalize_package_name(stripped)
    return _normalize_package_name("my-mcp-server")


def _write_init_pyproject(target: Path, *, package: str, force: bool) -> None:
    gdansk_document = rtoml.loads(_template_text("gdansk_tables.toml", package=package))

    if target.exists():
        document = read_pyproject_document(target.parent)
        if _gdansk_table(document) is not None and not force:
            msg = f"[gdansk] already present in {target}; use --force to replace gdansk tables"
            raise ProjectError(msg)
        if isinstance(document.get("belgie"), dict) and not force:
            raise _legacy_belgie_error(target.parent)
        document.pop("belgie", None)
    else:
        document = rtoml.loads(_template_text("pyproject.toml", package=package))

    document["gdansk"] = gdansk_document["gdansk"]
    write_pyproject_document(target.parent, document)


def _write_scaffold_file(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and not force:
        msg = f"Refusing to overwrite existing file: {path}"
        raise ProjectError(msg)
    atomic_write_text(path, content)


@app.command()
def init(
    path: Annotated[Path, typer.Option("--path", help="Directory to initialize")] = Path(),
    package: Annotated[
        str | None,
        typer.Option(
            "--package",
            help="Python package directory name under src/ (default: normalized [project].name)",
        ),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing scaffold files and gdansk tables")] = False,
    no_lock: Annotated[bool, typer.Option("--no-lock", help="Skip post-init dependency locking")] = False,
) -> None:
    target_dir = path.resolve()
    resolved_package = package if package is not None else _default_init_package(target_dir)
    package_root = target_dir / "src" / resolved_package
    main_path = package_root / "__main__.py"
    views_path = package_root / "views"

    if main_path.exists() and not force:
        eprint(f"Refusing to overwrite existing entrypoint: {main_path}")
        raise SystemExit(1)

    if views_path.exists() and any(views_path.iterdir()) and not force:
        eprint(f"Refusing to scaffold into non-empty views directory: {views_path}")
        raise SystemExit(1)

    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        _write_init_pyproject(target_dir / "pyproject.toml", package=resolved_package, force=force)
        _write_scaffold_file(
            package_root / "__init__.py",
            _template_text("__init__.py", package=resolved_package),
            force=force,
        )
        _write_scaffold_file(
            main_path,
            _template_text("__main__.py", package=resolved_package),
            force=force,
        )
        _write_scaffold_file(
            views_path / "widgets" / "hello" / "widget.tsx",
            _template_text("widget.tsx"),
            force=force,
        )
    except ProjectError as exc:
        eprint(str(exc))
        raise SystemExit(1) from exc

    project = load_project(target_dir)
    if not no_lock:
        import gdansk.cli

        with runtime_errors():
            gdansk.cli.lock_project(project)

    print(f"Initialized gdansk project in {target_dir}")
    print("Next steps:")
    print("  uv run gdansk dev")
    print(f"  uv run python -m {resolved_package}")
