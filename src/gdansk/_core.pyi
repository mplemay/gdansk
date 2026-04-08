from collections.abc import Sequence
from pathlib import Path

from gdansk_bundler import Plugin

class Page:
    def __init__(self, *, path: Path, is_widget: bool = False, ssr: bool = False) -> None: ...
    path: Path
    is_widget: bool
    ssr: bool
    client: Path
    server: Path | None
    css: Path

class LightningCSS(Plugin):
    def __init__(self) -> None: ...

async def bundle(
    pages: Sequence[Page],
    dev: bool = False,
    minify: bool = True,
    output: Path = ...,
    cwd: Path = ...,
    plugins: Sequence[Plugin] | None = None,
) -> None: ...
async def run(code: str, /) -> object: ...
