from __future__ import annotations

import asyncio
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gdansk._core import bundle

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from mcp.server.fastmcp import FastMCP
    from mcp.types import AnyFunction, Icon, ToolAnnotations

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light dark">
{css}</head>
<body>
<div id="root"></div>
<script type="module">
{js}
</script>
</body>
</html>"""


@dataclass(frozen=True, slots=True)
class Amber:
    mcp: FastMCP
    views: Path
    output: Path = field(default=Path(".gdansk"), kw_only=True)
    _paths: set[Path] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        if not self.views.is_dir():
            msg = f"The views directory {self.views} does not exist"
            raise ValueError(msg)

        if self.output.suffix != "":
            msg = f"The output directory {self.output} does not exist"
            raise ValueError(msg)

    @property
    def paths(self) -> frozenset[Path]:
        return frozenset(self._paths)

    @contextmanager
    def __call__(self, *, dev: bool = False, blocking: bool = False) -> Generator[None]:
        if not self._paths:
            return

        if (loop := asyncio.get_event_loop()).is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # Wraps the PyO3 async function so it's called inside a running event loop.
        async def _bundle() -> None:
            await bundle(paths=self._paths, dev=dev, output=self.output)

        task = loop.create_task(_bundle())

        try:
            if blocking:
                loop.run_until_complete(task)

            yield
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    loop.run_until_complete(task)

    def tool(  # noqa: PLR0913
        self,
        ui: Path,
        name: str | None = None,
        *,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: dict[str, Any] | None = None,
        structured_output: bool | None = None,
    ) -> Callable[[AnyFunction], AnyFunction]:
        if ui.suffix not in {".tsx", ".jsx"}:
            msg = f"The ui (i.e. {ui}) must be a .tsx or .jsx file"
            raise ValueError(msg)

        if not (self.views / ui).is_file():
            msg = f"The ui (i.e. {ui}) was not found"
            raise FileNotFoundError(msg)

        self._paths.add(ui)

        # my/page.tsx -> ui://my/page
        uri = f"ui://{ui.parent / ui.stem}"

        # add the ui to the metadata
        meta = meta or {}
        meta["ui"] = {"resourceUri": uri}

        def decorator(fn: AnyFunction) -> AnyFunction:
            self.mcp.tool(
                name=name,
                title=title,
                description=description,
                annotations=annotations,
                icons=icons,
                meta=meta,
                structured_output=structured_output,
            )(fn)

            @self.mcp.resource(uri=uri, mime_type="text/html;profile=mcp-app")
            def _() -> str:
                js = (self.output / ui.with_suffix(".js")).read_text(encoding="utf-8")
                if (path := self.output / ui.with_suffix(".css")).exists():
                    css = f"<style>\n{path.read_text(encoding='utf-8')}\n</style>\n"
                else:
                    css = ""
                return _HTML_TEMPLATE.format(js=js, css=css)

            return fn

        return decorator
