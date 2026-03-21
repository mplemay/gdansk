from collections.abc import Sequence
from os import PathLike
from pathlib import Path

class Page:
    def __init__(self, *, path: Path, app: bool = False, ssr: bool = False) -> None: ...
    path: Path
    app: bool
    ssr: bool
    client: Path
    server: Path | None
    css: Path

class LightningCSS:
    def __init__(self) -> None: ...
    id: str

class VitePlugin:
    def __init__(self, *, specifier: str | PathLike[str], options: object = ...) -> None: ...
    specifier: str
    options: object

async def bundle(
    pages: Sequence[Page],
    dev: bool = False,
    minify: bool = True,
    output: Path = ...,
    cwd: Path = ...,
    plugins: Sequence[LightningCSS | VitePlugin] | None = None,
) -> None: ...
async def run(code: str, /) -> object: ...
