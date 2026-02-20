from collections.abc import Sequence
from pathlib import Path

class View:
    def __init__(self, *, path: Path, app: bool = False, ssr: bool = False) -> None: ...
    path: Path
    app: bool
    ssr: bool
    client: Path
    server: Path | None
    css: Path

async def bundle(
    views: Sequence[View],
    dev: bool = False,
    minify: bool = True,
    output: Path = ...,
    cwd: Path = ...,
) -> None: ...
async def run(code: str, /) -> object: ...
