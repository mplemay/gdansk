from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

class BundleView(Protocol):
    path: Path
    app: bool
    ssr: bool

async def bundle(
    views: Sequence[BundleView],
    dev: bool = False,
    minify: bool = True,
    output: Path = ...,
    cwd: Path = ...,
) -> None: ...
async def run(code: str, /) -> object: ...
