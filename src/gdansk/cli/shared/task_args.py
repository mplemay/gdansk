from __future__ import annotations

from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from collections.abc import Sequence


def split_task_args(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    if "--" not in argv:
        return list(argv), []
    index = argv.index("--")
    return list(argv[:index]), list(argv[index + 1 :])


def task_args_from_context(ctx: typer.Context) -> list[str]:
    obj = ctx.obj
    if not isinstance(obj, dict):
        return []
    task_args = obj.get("task_args")
    if not isinstance(task_args, list):
        return []
    return task_args
