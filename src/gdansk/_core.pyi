from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, TypedDict

class BundleView(Protocol):
    path: Path
    app: bool
    ssr: bool

class BundleManifestEntry(TypedDict):
    client_js: str
    client_css: str
    server_js: str | None

async def bundle(
    views: Sequence[BundleView],
    dev: bool = False,
    minify: bool = True,
    output: Path = ...,
    cwd: Path = ...,
) -> dict[str, BundleManifestEntry]: ...
async def run(code: str, /) -> object: ...
