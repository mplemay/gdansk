from pathlib import Path

async def bundle(
    paths: set[Path],
    dev: bool = False,
    minify: bool = True,
    output: Path = ...,
    cwd: Path = ...,
    app_entrypoint_mode: bool = False,
    server_entrypoint_mode: bool = False,
) -> None: ...
async def run(code: str, /) -> object: ...
