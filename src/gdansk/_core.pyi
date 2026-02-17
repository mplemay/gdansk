from pathlib import Path

async def bundle(
    paths: set[Path],
    dev: bool = False,
    minify: bool = True,
    output: Path = ...,
    cwd: Path = ...,
) -> None: ...
