from __future__ import annotations

import importlib.metadata
import sys
from typing import TYPE_CHECKING, Annotated

import typer

from gdansk._project import ProjectError
from gdansk.cli.add import app as add_app
from gdansk.cli.build import app as build_app
from gdansk.cli.commands import app as commands_app
from gdansk.cli.dev import app as dev_app
from gdansk.cli.doctor import app as doctor_app
from gdansk.cli.init import app as init_app
from gdansk.cli.lock import app as lock_app
from gdansk.cli.run import app as run_app
from gdansk.cli.shared import split_task_args
from gdansk.cli.shared.errors import eprint
from gdansk.cli.update import app as update_app

if TYPE_CHECKING:
    from collections.abc import Sequence

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    name="gdansk",
    help="Gdansk project tooling",
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"gdansk {importlib.metadata.version('gdansk')}")
        raise typer.Exit


@app.callback()
def root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the gdansk version and exit.",
        ),
    ] = False,
) -> None:
    pass


SUBCOMMAND_APPS = (
    add_app,
    lock_app,
    update_app,
    build_app,
    dev_app,
    run_app,
    commands_app,
    doctor_app,
    init_app,
)
for subcommand_app in SUBCOMMAND_APPS:
    app.add_typer(subcommand_app)


def main(argv: Sequence[str] | None = None) -> None:
    cli_argv, task_args = split_task_args(sys.argv[1:] if argv is None else argv)
    try:
        app(
            cli_argv,
            prog_name="gdansk",
            obj={"task_args": task_args},
        )
    except ProjectError as exc:
        eprint(str(exc))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
