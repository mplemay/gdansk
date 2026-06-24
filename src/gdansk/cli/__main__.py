from __future__ import annotations

import importlib.metadata
import sys
from typing import TYPE_CHECKING, Annotated

import typer

from gdansk._project import ProjectError
from gdansk.cli._task_args import split_task_args
from gdansk.cli.add import app as add_app
from gdansk.cli.build import app as build_app
from gdansk.cli.commands import app as commands_app
from gdansk.cli.dev import app as dev_app
from gdansk.cli.doctor import app as doctor_app
from gdansk.cli.init import app as init_app
from gdansk.cli.lock import app as lock_app
from gdansk.cli.run import app as run_app
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


app.add_typer(add_app)
app.add_typer(lock_app)
app.add_typer(update_app)
app.add_typer(build_app)
app.add_typer(dev_app)
app.add_typer(run_app)
app.add_typer(commands_app)
app.add_typer(doctor_app)
app.add_typer(init_app)


def main(argv: Sequence[str] | None = None) -> None:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    cli_argv, task_args = split_task_args(raw_argv)
    try:
        app(
            cli_argv,
            prog_name="gdansk",
            obj={"task_args": task_args},
        )
    except ProjectError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    main()
