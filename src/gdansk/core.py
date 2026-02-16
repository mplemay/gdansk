from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, ClassVar

from anyio import Path as APath

from gdansk._core import bundle
from gdansk.metadata import Metadata, merge_metadata
from gdansk.render import ENV

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from mcp.server.fastmcp import FastMCP
    from mcp.types import AnyFunction, Icon, ToolAnnotations


@dataclass(frozen=True, slots=True)
class Amber:
    _paths: set[Path] = field(default_factory=set, init=False)
    _template: ClassVar[str] = "template.html"
    _env: ClassVar = ENV

    mcp: FastMCP
    views: Path
    output: Path = field(default=Path(".gdansk"), kw_only=True)
    metadata: Metadata | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if not self.views.is_dir():
            msg = f"The views directory {self.views} does not exist"
            raise ValueError(msg)

        if self.output.suffix != "":
            msg = f"The output directory {self.output} does not exist"
            raise ValueError(msg)

        if not self.output.is_absolute():
            object.__setattr__(self, "output", Path.cwd() / self.output)

    @property
    def paths(self) -> frozenset[Path]:
        return frozenset(self._paths)

    @contextmanager
    def __call__(self, *, dev: bool = False, blocking: bool = False) -> Generator[None]:
        if not self._paths:
            yield
            return

        loop = asyncio.new_event_loop()

        async def _bundle() -> None:
            await bundle(paths=self._paths, dev=dev, output=self.output, cwd=self.views)

        task = loop.create_task(_bundle())
        thread: threading.Thread | None = None

        if blocking:
            loop.run_until_complete(task)
        else:
            thread = threading.Thread(target=loop.run_forever, daemon=True)
            thread.start()

        try:
            yield
        finally:
            if not task.done():
                loop.call_soon_threadsafe(task.cancel)
            if thread is not None:
                loop.call_soon_threadsafe(loop.stop)
                thread.join()
            if not task.done():
                with suppress(asyncio.CancelledError):
                    loop.run_until_complete(task)
            loop.close()

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
        metadata: Metadata | None = None,
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
        uri = f"ui://{PurePosixPath(ui.parent, ui.stem)}"

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

            @self.mcp.resource(
                uri=uri,
                name=name,
                title=title,
                description=description,
                mime_type="text/html;profile=mcp-app",
            )
            async def _() -> str:
                try:
                    js = await APath(self.output / ui.with_suffix(".js")).read_text(encoding="utf-8")
                except FileNotFoundError:
                    msg = f"Bundled output for {ui} not found. Has the bundler been run?"
                    raise FileNotFoundError(msg) from None
                css = (
                    None
                    if not await (path := APath(self.output / ui.with_suffix(".css"))).exists()
                    else await path.read_text(encoding="utf-8")
                )

                return Amber._env.render_template(
                    Amber._template,
                    js=js,
                    css=css,
                    metadata=merge_metadata(self.metadata, metadata),
                )

            return fn

        return decorator
