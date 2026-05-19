from collections.abc import Sequence
from pathlib import Path

class BundleWidget:
    def __init__(self, *, key: str, path: Path) -> None: ...
    key: str
    path: Path

async def bundle(
    widgets: Sequence[BundleWidget],
    *,
    root: Path,
    build_directory: str = "dist",
    minify: bool = True,
) -> None: ...
def hello_from_bin() -> str: ...
