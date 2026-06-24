from __future__ import annotations

import typer

from gdansk.cli.shared.task_args import split_task_args, task_args_from_context


def _context(*, obj: object | None = None) -> typer.Context:
    app = typer.Typer()

    @app.command()
    def noop() -> None:
        pass

    return typer.Context(typer.main.get_command(app), obj=obj)


def test_split_task_args_without_separator():
    cli_argv, task_args = split_task_args(["build", "--frontend", "views"])
    assert cli_argv == ["build", "--frontend", "views"]
    assert task_args == []


def test_split_task_args_with_separator():
    cli_argv, task_args = split_task_args(["build", "--", "--emptyOutDir"])
    assert cli_argv == ["build"]
    assert task_args == ["--emptyOutDir"]


def test_split_task_args_with_multiple_separators_uses_first():
    cli_argv, task_args = split_task_args(["run", "cmd", "--", "a", "--", "b"])
    assert cli_argv == ["run", "cmd"]
    assert task_args == ["a", "--", "b"]


def test_task_args_from_context_missing_obj():
    assert task_args_from_context(_context()) == []


def test_task_args_from_context_non_dict_obj():
    assert task_args_from_context(_context(obj="not-a-dict")) == []


def test_task_args_from_context_non_list_task_args():
    assert task_args_from_context(_context(obj={"task_args": "bad"})) == []


def test_task_args_from_context_valid_list():
    assert task_args_from_context(_context(obj={"task_args": ["--open"]})) == ["--open"]
