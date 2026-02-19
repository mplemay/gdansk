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

class Runtime:
    def __init__(self) -> None: ...
    def __call__(self, code: str, /) -> object: ...
    def render_ssr(self, code: str, /) -> str: ...
