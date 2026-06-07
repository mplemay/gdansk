from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import re
import shutil
import signal
import sys
import tomllib
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

from gdansk import GdanskRuntimeError, install_packages, lock_packages, update_packages
from gdansk._project import (
    GdanskProject,
    ProjectError,
    discover_project,
    load_project,
    resolve_frontend_path,
    validate_frontend_root,
)
from gdansk.task import run_task, start_task

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence

    from gdansk._core import TaskProcess

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 13_714
PYTHON_MIN = (3, 12)
PYTHON_MAX = (3, 15)


def _template_text(name: str, *, frontend_dir: str = "frontend") -> str:
    raw = resources.files("gdansk._cli_templates").joinpath(name).read_text(encoding="utf-8")
    return raw.replace("{{FRONTEND_DIR}}", frontend_dir)


def _eprint(message: str) -> None:
    print(message, file=sys.stderr)


def _resolve_project(project: Path | None, start: Path | None = None) -> GdanskProject:
    return discover_project(project=project, start=start or Path.cwd())


def _resolve_task_frontend(
    project: GdanskProject,
    frontend: Path | None,
) -> Path:
    frontend_path = resolve_frontend_path(project, frontend)
    validate_frontend_root(frontend_path)
    return frontend_path


def _require_script(project: GdanskProject, script: str) -> None:
    if script in project.scripts:
        return

    _eprint(f"No [gdansk.scripts] entry '{script}' in {project.root / 'pyproject.toml'}")
    if project.scripts:
        _eprint("Available scripts:")
        for name, command in sorted(project.scripts.items()):
            print(f"  {name}  {command}", file=sys.stderr)
    else:
        _eprint("Run `gdansk scripts` to list configured scripts.")
    raise SystemExit(1)


def _dev_argv(host: str, port: int) -> list[str]:
    return ["--host", host, "--port", str(port)]


async def _run_until_signal(coro: Awaitable[TaskProcess]) -> None:
    process: TaskProcess | None = None
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda _signum, _frame: request_stop())

    try:
        process = await coro
        await stop_event.wait()
    finally:
        if process is not None:
            await process.stop()


def cmd_install(args: argparse.Namespace) -> None:
    project = _resolve_project(args.project)
    try:
        result = install_packages(
            cwd=project.root,
            include_dev=not args.no_dev,
            lockfile_only=args.lock_only,
        )
    except GdanskRuntimeError as error:
        _eprint(str(error))
        raise SystemExit(1) from error

    dev_suffix = f" (+{result.dev_dependencies} dev)" if result.dev_dependencies else ""
    print(f"Installed {result.dependencies} dependencies{dev_suffix}. Lockfile: {result.lockfile}")


def cmd_lock(args: argparse.Namespace) -> None:
    project = _resolve_project(args.project)
    try:
        result = lock_packages(cwd=project.root, include_dev=not args.no_dev)
    except GdanskRuntimeError as error:
        _eprint(str(error))
        raise SystemExit(1) from error

    dev_suffix = f" (+{result.dev_dependencies} dev)" if result.dev_dependencies else ""
    print(f"Locked {result.dependencies} dependencies{dev_suffix}. Lockfile: {result.lockfile}")


def cmd_update(args: argparse.Namespace) -> None:
    project = _resolve_project(args.project)
    try:
        result = update_packages(
            cwd=project.root,
            packages=args.packages or None,
            include_dev=not args.no_dev,
            latest=args.latest,
            lockfile_only=args.lock_only,
        )
    except GdanskRuntimeError as error:
        _eprint(str(error))
        raise SystemExit(1) from error

    for change in result.changes:
        print(f"{change.name}: {change.previous} -> {change.updated}")
    print(f"Lockfile: {result.lockfile}")


def _run_task_command(
    args: argparse.Namespace,
    *,
    script: str,
    long_running: bool,
) -> None:
    project = _resolve_project(args.project)
    _require_script(project, script)

    frontend_path = _resolve_task_frontend(project, args.frontend)
    argv = list(args.task_args)
    host = getattr(args, "host", DEFAULT_HOST)
    port = getattr(args, "port", DEFAULT_PORT)

    try:
        if long_running:
            task_argv = _dev_argv(host, port) + argv if script == "dev" else argv
            task_coro = start_task(
                frontend_path,
                script,
                argv=task_argv,
                host=host,
                port=port,
            )
            asyncio.run(_run_until_signal(task_coro))
        else:
            asyncio.run(run_task(frontend_path, script, argv=argv))
    except GdanskRuntimeError as error:
        _eprint(str(error))
        raise SystemExit(1) from error


def cmd_build(args: argparse.Namespace) -> None:
    _run_task_command(args, script="build", long_running=False)


def cmd_dev(args: argparse.Namespace) -> None:
    _run_task_command(args, script="dev", long_running=True)


def cmd_run(args: argparse.Namespace) -> None:
    long_running = args.script == "dev" or args.watch
    _run_task_command(args, script=args.script, long_running=long_running)


def cmd_scripts(args: argparse.Namespace) -> None:
    project = _resolve_project(args.project)
    if not project.scripts:
        _eprint("No [gdansk.scripts] entries configured.")
        raise SystemExit(1)

    width = max(len(name) for name in project.scripts)
    for name, command in sorted(project.scripts.items()):
        print(f"{name:<{width}}  {command}")


def _check_deno_available() -> tuple[str, str]:
    deno_env = __import__("os").environ.get("GDANSK_DENO")
    if deno_env:
        path = Path(deno_env)
        if path.is_file():
            return ("ok", f"deno executable ({path})")
        return ("fail", f"GDANSK_DENO points to a missing executable: {path}")

    deno = shutil.which("deno")
    if deno:
        return ("ok", f"deno executable ({deno})")
    return ("fail", "deno executable not found on PATH (set GDANSK_DENO or install Deno)")


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

    deno_status, deno_message = _check_deno_available()
    print(f"{deno_status}  {deno_message}")
    if deno_status == "fail":
        failures.append(deno_message)

    try:
        project = _resolve_project(args.project)
    except ProjectError as error:
        print(f"fail {error}")
        failures.append(str(error))
        project = None

    if project is not None:
        if project.has_dependencies:
            print(f"ok   [gdansk.dependencies] in {project.root / 'pyproject.toml'}")
        else:
            message = "No [gdansk.dependencies] table found"
            print(f"fail {message}")
            failures.append(message)

        try:
            frontend_path = resolve_frontend_path(project, args.frontend)
        except ProjectError as error:
            print(f"fail {error}")
            failures.append(str(error))
            frontend_path = None

        if frontend_path is not None:
            if frontend_path.exists() and frontend_path.is_dir():
                print(f"ok   frontend root ({frontend_path})")
            else:
                message = f"Frontend root does not exist: {frontend_path}"
                print(f"fail {message}")
                failures.append(message)

            try:
                frontend_warnings = validate_frontend_root(frontend_path)
            except ProjectError as error:
                print(f"fail {error}")
                failures.append(str(error))
                frontend_warnings = []
            else:
                print(f"ok   vite.config.ts and widgets/ in {frontend_path}")
                warnings.extend(frontend_warnings)

            root_lock = project.root / "deno.lock"
            if root_lock.is_file():
                print(f"ok   deno.lock at project root ({root_lock})")
            else:
                message = f"deno.lock missing at project root ({root_lock})"
                print(f"warn {message}")
                warnings.append(message)

            if frontend_path is not None:
                legacy_lock = frontend_path / "deno.lock"
                if legacy_lock.is_file() and not root_lock.is_file():
                    message = f"Legacy deno.lock found under frontend ({legacy_lock}); move it to the project root"
                    print(f"warn {message}")
                    warnings.append(message)

            for script_name in ("build", "dev"):
                if script_name in project.scripts:
                    print(f"ok   [gdansk.scripts].{script_name}")
                else:
                    message = f"Missing [gdansk.scripts].{script_name}"
                    print(f"warn {message}")
                    warnings.append(message)

    for warning in warnings:
        _eprint(f"warning: {warning}")

    if failures:
        _eprint(f"doctor: {len(failures)} check(s) failed")
        raise SystemExit(1)

    if warnings:
        print(f"doctor: {len(warnings)} warning(s)")
    else:
        print("doctor: all checks passed")


def _pyproject_has_gdansk(path: Path) -> bool:
    if not path.is_file():
        return False
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    return "gdansk" in document


def _strip_gdansk_sections(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    skipping = False

    for line in lines:
        if re.match(r"^\[gdansk(?:\.[^\]]+)?\]\s*$", line):
            skipping = True
            continue
        if line.startswith("[") and not line.startswith("[gdansk"):
            skipping = False
        if not skipping:
            kept.append(line)

    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept) + "\n"


def _write_init_pyproject(target: Path, *, frontend_dir: str, force: bool) -> None:
    if target.exists():
        text = target.read_text(encoding="utf-8")
        if _pyproject_has_gdansk(target) and not force:
            msg = f"[gdansk] already present in {target}; use --force to replace gdansk tables"
            raise ProjectError(msg)
        if _pyproject_has_gdansk(target) and force:
            text = _strip_gdansk_sections(text)
            text = text.rstrip() + "\n\n" + _template_text("gdansk_tables.toml", frontend_dir=frontend_dir)
            target.write_text(text, encoding="utf-8")
            return
        text = text.rstrip() + "\n\n" + _template_text("gdansk_tables.toml", frontend_dir=frontend_dir)
        target.write_text(text, encoding="utf-8")
        return

    target.write_text(_template_text("pyproject.toml", frontend_dir=frontend_dir), encoding="utf-8")


def _write_scaffold_file(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and not force:
        msg = f"Refusing to overwrite existing file: {path}"
        raise ProjectError(msg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def cmd_init(args: argparse.Namespace) -> None:
    target_dir = Path(args.path).resolve()
    frontend_dir = args.frontend
    frontend_path = target_dir / frontend_dir

    if (target_dir / "server.py").exists() and not args.force:
        msg = f"Refusing to overwrite existing server.py in {target_dir}"
        _eprint(msg)
        raise SystemExit(1)

    if frontend_path.exists() and any(frontend_path.iterdir()) and not args.force:
        msg = f"Refusing to scaffold into non-empty frontend directory: {frontend_path}"
        _eprint(msg)
        raise SystemExit(1)

    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        _write_init_pyproject(target_dir / "pyproject.toml", frontend_dir=frontend_dir, force=args.force)
        _write_scaffold_file(
            target_dir / "server.py",
            _template_text("server.py", frontend_dir=frontend_dir),
            force=args.force,
        )
        _write_scaffold_file(
            frontend_path / "package.json",
            _template_text("package.json"),
            force=args.force,
        )
        _write_scaffold_file(
            frontend_path / "vite.config.ts",
            _template_text("vite.config.ts"),
            force=args.force,
        )
        _write_scaffold_file(
            frontend_path / "widgets" / "hello" / "widget.tsx",
            _template_text("widget.tsx"),
            force=args.force,
        )
    except ProjectError as error:
        _eprint(str(error))
        raise SystemExit(1) from error

    project = load_project(target_dir)
    if not args.no_install:
        try:
            lock_packages(cwd=project.root)
        except GdanskRuntimeError as error:
            _eprint(str(error))
            raise SystemExit(1) from error

    print(f"Initialized gdansk project in {target_dir}")
    print("Next steps:")
    print("  uv run gdansk install")
    print("  uv run gdansk dev")
    print("  uv run python server.py")


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
        help="Frontend package root (overrides [gdansk] frontend)",
    )


def _add_dev_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=DEFAULT_HOST, help="Dev server host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Dev server port")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gdansk", description="Gdansk project tooling")
    parser.add_argument("--version", action="version", version=f"gdansk {importlib.metadata.version('gdansk')}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser("install", help="Install [gdansk.dependencies]")
    _add_project_args(install)
    install.add_argument("--no-dev", action="store_true", help="Skip [gdansk.dev-dependencies]")
    install.add_argument("--lock-only", action="store_true", help="Update deno.lock without caching packages")
    install.set_defaults(func=cmd_install)

    lock = subparsers.add_parser("lock", help="Update deno.lock without installing packages")
    _add_project_args(lock)
    lock.add_argument("--no-dev", action="store_true", help="Skip [gdansk.dev-dependencies]")
    lock.set_defaults(func=cmd_lock)

    update = subparsers.add_parser("update", help="Update [gdansk.dependencies]")
    _add_project_args(update)
    update.add_argument("packages", nargs="*", help="Optional package names to update")
    update.add_argument("--no-dev", action="store_true", help="Skip [gdansk.dev-dependencies]")
    update.add_argument("--latest", action="store_true", help="Update to the latest versions")
    update.add_argument("--lock-only", action="store_true", help="Update lockfile without caching packages")
    update.set_defaults(func=cmd_update)

    build = subparsers.add_parser("build", help="Run [gdansk.scripts].build")
    _add_project_args(build)
    _add_frontend_args(build)
    build.set_defaults(func=cmd_build)

    dev = subparsers.add_parser("dev", help="Run [gdansk.scripts].dev")
    _add_project_args(dev)
    _add_frontend_args(dev)
    _add_dev_runtime_args(dev)
    dev.set_defaults(func=cmd_dev)

    run = subparsers.add_parser("run", help="Run a [gdansk.scripts] entry")
    _add_project_args(run)
    _add_frontend_args(run)
    _add_dev_runtime_args(run)
    run.add_argument("script", help="Script name from [gdansk.scripts]")
    run.add_argument("--watch", action="store_true", help="Keep the task running until interrupted")
    run.set_defaults(func=cmd_run)

    scripts = subparsers.add_parser("scripts", help="List [gdansk.scripts] entries")
    _add_project_args(scripts)
    scripts.set_defaults(func=cmd_scripts)

    doctor = subparsers.add_parser("doctor", help="Validate environment and project layout")
    _add_project_args(doctor)
    _add_frontend_args(doctor)
    doctor.set_defaults(func=cmd_doctor)

    init = subparsers.add_parser("init", help="Scaffold a minimal gdansk MCP app")
    init.add_argument("--path", type=Path, default=Path(), help="Directory to initialize")
    init.add_argument("--frontend", default="frontend", help="Frontend directory name")
    init.add_argument("--force", action="store_true", help="Overwrite existing scaffold files")
    init.add_argument("--no-install", action="store_true", help="Skip post-init lock")
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
    except ProjectError as error:
        _eprint(str(error))
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
