from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

ProjectDir = Annotated[
    Path | None,
    typer.Option(
        "-C",
        "--project",
        help="Project root containing pyproject.toml with [gdansk] configuration",
    ),
]

FrontendDir = Annotated[
    Path | None,
    typer.Option(
        "-F",
        "--frontend",
        help="Frontend root (overrides auto-discovered src/<package>/views)",
    ),
]
