from collections.abc import Sequence
from pathlib import Path

class Page:
    def __init__(self, *, path: Path, app: bool = False, ssr: bool = False) -> None: ...
    path: Path
    app: bool
    ssr: bool
    client: Path
    server: Path | None
    css: Path

class JsPluginRunner:
    def __init__(self, specs_json: str, /) -> None: ...
    async def build(self, *, pages: Path, output: Path) -> None: ...
    def close(self) -> None: ...

async def bundle(
    pages: Sequence[Page],
    dev: bool = False,
    minify: bool = True,
    output: Path = ...,
    cwd: Path = ...,
) -> None: ...
async def _bundle_with_plugins(
    pages: Sequence[Page],
    plugins: Sequence[str],
    dev: bool = False,
    minify: bool = True,
    output: Path = ...,
    cwd: Path = ...,
) -> None: ...
async def run(code: str, /) -> object: ...
