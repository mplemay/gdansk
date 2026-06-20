from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import shlex
import signal
import sys
from contextlib import contextmanager, suppress
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Final

import rtoml
from belgie.errors import BelgieRuntimeError

from gdansk._project import (
    GdanskProject,
    ProjectError,
    _gdansk_table,
    _legacy_belgie_error,
    atomic_write_text,
    discover_project,
    load_project,
    read_pyproject_document,
    resolve_frontend_path,
    validate_frontend_root,
    write_pyproject_document,
)
from gdansk.packages import add_dependency, lock_project, update_project
from gdansk.task import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    CommandProcess,
    dev_command_argv,
    run_command,
    start_command,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Generator, Sequence

PYTHON_MIN: Final[tuple[int, int]] = (3, 12)
PYTHON_MAX: Final[tuple[int, int]] = (3, 15)


def _normalize_package_name(name: str) -> str:
    return name.replace("-", "_")


def _template_text(name: str, *, package: str = "my_mcp_server") -> str:
    raw = resources.files("gdansk._cli_templates").joinpath(name).read_text(encoding="utf-8")
    return raw.replace("{{PACKAGE}}", package)


def _default_init_package(target_dir: Path) -> str:
    pyproject_path = target_dir / "pyproject.toml"
    if pyproject_path.is_file():
        document = read_pyproject_document(target_dir)
        project = document.get("project")
        if isinstance(project, dict):
            name = project.get("name")
            if isinstance(name, str) and name.strip():
                return _normalize_package_name(name.strip())
    return _normalize_package_name("my-mcp-server")


def _resolve_init_package(args: argparse.Namespace, target_dir: Path) -> str:
    if args.package is not None:
        return args.package
    return _default_init_package(target_dir)


def _eprint(message: str) -> None:
    print(message, file=sys.stderr)


@contextmanager
def _runtime_errors() -> Generator[None, None, None]:
    try:
        yield
    except BelgieRuntimeError as exc:
        _eprint(str(exc))
        raise SystemExit(1) from exc


def _resolve_frontend(project: GdanskProject, frontend: Path | None) -> Path:
    frontend_path = resolve_frontend_path(project, frontend)
    validate_frontend_root(frontend_path)
    return frontend_path


def _require_command(project: GdanskProject, name: str) -> tuple[str, ...]:
    command = project.commands.get(name)
    if command is not None:
        return command

    _eprint(f"No [gdansk.commands] entry '{name}' in {project.root / 'pyproject.toml'}")
    if project.commands:
        _eprint("Available commands:")
        for command_name, command_argv in sorted(project.commands.items()):
            _eprint(f"  {command_name}  {shlex.join(command_argv)}")
    raise SystemExit(1)


async def _run_until_signal(process_awaitable: Awaitable[CommandProcess]) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        loop.call_soon_threadsafe(stop_event.set)

    signals: list[signal.Signals] = [signal.SIGINT, signal.SIGTERM]
    if sys.platform == "win32":
        signals.append(signal.SIGBREAK)

    registered: list[signal.Signals] = []
    for current_signal in signals:
        try:
            loop.add_signal_handler(current_signal, request_stop)
            registered.append(current_signal)
        except NotImplementedError:
            signal.signal(current_signal, lambda _signum, _frame: request_stop())

    process: CommandProcess | None = None
    stop_waiter: asyncio.Task[bool] | None = None
    try:
        process = await process_awaitable
        stop_waiter = asyncio.create_task(stop_event.wait())
        done, _ = await asyncio.wait(
            {process.task, stop_waiter},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_waiter in done:
            await process.stop()
        else:
            await process.wait()
    finally:
        if process is not None and process.is_running:
            await process.stop()
        if stop_waiter is not None:
            stop_waiter.cancel()
            with suppress(asyncio.CancelledError):
                await stop_waiter
        for current_signal in registered:
            loop.remove_signal_handler(current_signal)


def cmd_add(args: argparse.Namespace) -> None:
    project = discover_project(project=args.project)
    with _runtime_errors():
        add_dependency(
            project,
            alias=args.alias,
            specifier=args.specifier,
            dev=args.dev,
        )
    group = "dev" if args.dev else "default"
    print(f"Added {args.alias} to {group} dependencies. Lockfile: {project.lockfile_path}")


def cmd_lock(args: argparse.Namespace) -> None:
    project = discover_project(project=args.project)
    with _runtime_errors():
        result = lock_project(project)
    print(f"Locked {result.dependencies} dependencies. Lockfile: {project.lockfile_path}")


def cmd_update(args: argparse.Namespace) -> None:
    project = discover_project(project=args.project)
    with _runtime_errors():
        result = update_project(project, args.packages or None, latest=args.latest)
    for change in result.changes:
        print(f"{change.name}: {change.previous} -> {change.updated}")
    print(f"Lockfile: {project.lockfile_path}")


def cmd_build(args: argparse.Namespace) -> None:
    project = discover_project(project=args.project)
    frontend = _resolve_frontend(project, args.frontend)
    with _runtime_errors():
        asyncio.run(
            run_command(
                project,
                "vite",
                cwd=frontend,
                argv=["build", *args.task_args],
            ),
        )


def cmd_dev(args: argparse.Namespace) -> None:
    project = discover_project(project=args.project)
    frontend = _resolve_frontend(project, args.frontend)
    argv = [*dev_command_argv(args.host, args.port), *args.task_args]
    with _runtime_errors():
        asyncio.run(
            _run_until_signal(
                start_command(project, "vite", cwd=frontend, argv=argv),
            ),
        )


def cmd_run(args: argparse.Namespace) -> None:
    project = discover_project(project=args.project)
    configured = _require_command(project, args.name)
    command, *fixed_arguments = configured
    argv = [*fixed_arguments, *args.task_args]
    with _runtime_errors():
        if args.watch:
            asyncio.run(
                _run_until_signal(
                    start_command(project, command, cwd=project.root, argv=argv),
                ),
            )
        else:
            asyncio.run(
                run_command(project, command, cwd=project.root, argv=argv),
            )


def cmd_commands(args: argparse.Namespace) -> None:
    project = discover_project(project=args.project)
    if not project.commands:
        _eprint("No [gdansk.commands] entries configured.")
        raise SystemExit(1)

    width = max(len(name) for name in project.commands)
    for name, command in sorted(project.commands.items()):
        print(f"{name:<{width}}  {shlex.join(command)}")


def _doctor_warn(message: str, warnings: list[str]) -> None:
    warnings.append(message)


def _doctor_check_dependencies(project: GdanskProject, failures: list[str]) -> None:
    if project.has_dependencies:
        print(f"ok   [gdansk.dependencies] in {project.root / 'pyproject.toml'}")
        return

    message = "No [gdansk.dependencies] table found"
    print(f"fail {message}")
    failures.append(message)


def _doctor_check_frontend(
    project: GdanskProject,
    frontend: Path | None,
    failures: list[str],
    warnings: list[str],
) -> None:
    try:
        frontend_path = _resolve_frontend(project, frontend)
    except ProjectError as exc:
        print(f"fail {exc}")
        failures.append(str(exc))
        return

    print(f"ok   frontend root ({frontend_path})")

    root_lock = project.lockfile_path
    if root_lock.is_file():
        print(f"ok   gdansk lockfile (deno.lock) at project root ({root_lock})")
    else:
        message = f"gdansk lockfile (deno.lock) missing at project root ({root_lock})"
        _doctor_warn(message, warnings)

    legacy_lock = frontend_path / "deno.lock"
    if legacy_lock.is_file() and not root_lock.is_file():
        message = f"Legacy lockfile found under frontend ({legacy_lock}); move it to the project root"
        _doctor_warn(message, warnings)


def cmd_doctor(args: argparse.Namespace) -> None:
    failures: list[str] = []
    warnings: list[str] = []

    version = sys.version_info
    if version < PYTHON_MIN or version >= PYTHON_MAX:
        failures.append(
            f"Python {version.major}.{version.minor} (requires >={PYTHON_MIN[0]}.{PYTHON_MIN[1]},"
            f"<{PYTHON_MAX[0]}.{PYTHON_MAX[1]})",
        )
    else:
        print(f"ok   Python {version.major}.{version.minor}.{version.micro}")

    try:
        project = discover_project(project=args.project)
    except ProjectError as exc:
        print(f"fail {exc}")
        failures.append(str(exc))
    else:
        _doctor_check_dependencies(project, failures)
        _doctor_check_frontend(project, args.frontend, failures, warnings)

    for warning in warnings:
        _eprint(f"warning: {warning}")

    if failures:
        _eprint(f"doctor: {len(failures)} check(s) failed")
        raise SystemExit(1)

    if warnings:
        print(f"doctor: {len(warnings)} warning(s)")
    else:
        print("doctor: all checks passed")


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


def cmd_init(args: argparse.Namespace) -> None:
    target_dir = Path(args.path).resolve()
    package = _resolve_init_package(args, target_dir)
    package_root = target_dir / "src" / package
    main_path = package_root / "__main__.py"
    views_path = package_root / "views"

    if main_path.exists() and not args.force:
        _eprint(f"Refusing to overwrite existing entrypoint: {main_path}")
        raise SystemExit(1)

    if views_path.exists() and any(views_path.iterdir()) and not args.force:
        _eprint(f"Refusing to scaffold into non-empty views directory: {views_path}")
        raise SystemExit(1)

    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        _write_init_pyproject(target_dir / "pyproject.toml", package=package, force=args.force)
        _write_scaffold_file(
            package_root / "__init__.py",
            _template_text("__init__.py", package=package),
            force=args.force,
        )
        _write_scaffold_file(
            main_path,
            _template_text("__main__.py", package=package),
            force=args.force,
        )
        _write_scaffold_file(
            views_path / "vite.config.ts",
            _template_text("vite.config.ts"),
            force=args.force,
        )
        _write_scaffold_file(
            views_path / "widgets" / "hello" / "widget.tsx",
            _template_text("widget.tsx"),
            force=args.force,
        )
    except ProjectError as exc:
        _eprint(str(exc))
        raise SystemExit(1) from exc

    project = load_project(target_dir)
    if not args.no_lock:
        with _runtime_errors():
            lock_project(project)

    print(f"Initialized gdansk project in {target_dir}")
    print("Next steps:")
    print("  uv run gdansk dev")
    print(f"  uv run python -m {package}")


def _split_task_args(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    if "--" not in argv:
        return list(argv), []
    index = argv.index("--")
    return list(argv[:index]), list(argv[index + 1 :])


def _add_project_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-C",
        "--project",
        type=Path,
        default=None,
        help="Project root containing pyproject.toml with [gdansk] configuration",
    )


def _add_frontend_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-F",
        "--frontend",
        type=Path,
        default=None,
        help="Frontend root (overrides auto-discovered src/<package>/views)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gdansk", description="Gdansk project tooling")
    parser.add_argument("--version", action="version", version=f"gdansk {importlib.metadata.version('gdansk')}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add", help="Add a [gdansk.dependencies] entry and refresh deno.lock")
    _add_project_args(add)
    add.add_argument("alias", help="JavaScript import alias")
    add.add_argument("specifier", help="npm version requirement or full npm:/jsr: specifier")
    add.add_argument("--dev", action="store_true", help="Add to [gdansk.dependencies.dev]")
    add.set_defaults(func=cmd_add)

    lock = subparsers.add_parser("lock", help="Resolve dependencies and write deno.lock")
    _add_project_args(lock)
    lock.set_defaults(func=cmd_lock)

    update = subparsers.add_parser("update", help="Update [gdansk.dependencies]")
    _add_project_args(update)
    update.add_argument("packages", nargs="*", help="Optional dependency aliases to update")
    update.add_argument("--latest", action="store_true", help="Update to the latest versions")
    update.set_defaults(func=cmd_update)

    build = subparsers.add_parser("build", help="Build widgets with Vite")
    _add_project_args(build)
    _add_frontend_args(build)
    build.set_defaults(func=cmd_build)

    dev = subparsers.add_parser("dev", help="Run the Vite development server")
    _add_project_args(dev)
    _add_frontend_args(dev)
    dev.add_argument("--host", default=DEFAULT_HOST, help="Dev server host")
    dev.add_argument("--port", type=int, default=DEFAULT_PORT, help="Dev server port")
    dev.set_defaults(func=cmd_dev)

    run = subparsers.add_parser("run", help="Run a [gdansk.commands] entry")
    _add_project_args(run)
    run.add_argument("name", help="Command name from [gdansk.commands]")
    run.add_argument("--watch", action="store_true", help="Keep the command running until interrupted")
    run.set_defaults(func=cmd_run)

    commands = subparsers.add_parser("commands", help="List [gdansk.commands] entries")
    _add_project_args(commands)
    commands.set_defaults(func=cmd_commands)

    doctor = subparsers.add_parser("doctor", help="Validate environment and project layout")
    _add_project_args(doctor)
    _add_frontend_args(doctor)
    doctor.set_defaults(func=cmd_doctor)

    init = subparsers.add_parser("init", help="Scaffold a minimal gdansk MCP app")
    init.add_argument("--path", type=Path, default=Path(), help="Directory to initialize")
    init.add_argument(
        "--package",
        default=None,
        help="Python package directory name under src/ (default: normalized [project].name)",
    )
    init.add_argument("--force", action="store_true", help="Overwrite existing scaffold files and gdansk tables")
    init.add_argument("--no-lock", action="store_true", help="Skip post-init dependency locking")
    init.set_defaults(func=cmd_init)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    cli_argv, task_args = _split_task_args(raw_argv)

    parser = build_parser()
    args = parser.parse_args(cli_argv)
    args.task_args = task_args

    try:
        args.func(args)
    except ProjectError as exc:
        _eprint(str(exc))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
