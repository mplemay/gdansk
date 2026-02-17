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
    _ui_min_parts: ClassVar[int] = 2

    mcp: FastMCP
    views: Path
    output: Path = field(init=False)
    metadata: Metadata | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if not self.views.is_dir():
            msg = f"The views directory {self.views} does not exist"
            raise ValueError(msg)

        object.__setattr__(self, "output", self.views / ".gdansk")

    @property
    def paths(self) -> frozenset[Path]:
        return frozenset(self._paths)

    @staticmethod
    def _normalize_ui_path_and_uri(ui: Path) -> tuple[Path, Path, str]:
        if ui.suffix not in {".tsx", ".jsx"}:
            msg = f"The ui (i.e. {ui}) must be a .tsx or .jsx file"
            raise ValueError(msg)

        if ui.is_absolute():
            msg = f"The ui (i.e. {ui}) must be a relative path"
            raise ValueError(msg)

        ui_posix = PurePosixPath(ui.as_posix())
        if any(part in {"", ".", ".."} for part in ui_posix.parts):
            msg = f"The ui (i.e. {ui}) must not contain traversal segments"
            raise ValueError(msg)

        if (
            len(ui_posix.parts) < Amber._ui_min_parts
            or ui_posix.parts[0] == "apps"
            or ui_posix.name not in {"app.tsx", "app.jsx"}
        ):
            msg = f"The ui (i.e. {ui}) must match **/app.tsx or **/app.jsx and must not start with apps/"
            raise ValueError(msg)

        normalized_ui = Path(*ui_posix.parts)
        bundle_ui = Path("apps", *ui_posix.parts)
        uri = f"ui://{PurePosixPath(*ui_posix.parts[:-1])}"
        return normalized_ui, bundle_ui, uri

    @contextmanager
    def __call__(self, *, dev: bool = False, minify: bool | None = None, blocking: bool = False) -> Generator[None]:
        if not self._paths:
            yield
            return

        loop = asyncio.new_event_loop()
        bundle_paths = {Path("apps", *path.parts) for path in self._paths}
        resolved_minify = (not dev) if minify is None else minify

        async def _bundle() -> None:
            await bundle(
                paths=bundle_paths,
                dev=dev,
                minify=resolved_minify,
                output=self.output,
                cwd=self.views,
            )

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
        normalized_ui, bundle_ui, uri = self._normalize_ui_path_and_uri(ui)

        if not (self.views / bundle_ui).is_file():
            msg = f"The ui (i.e. {ui}) was not found"
            raise FileNotFoundError(msg)

        self._paths.add(normalized_ui)

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
                    js = await APath(self.output / bundle_ui.with_suffix(".js")).read_text(encoding="utf-8")
                except FileNotFoundError:
                    msg = f"Bundled output for {ui} not found. Has the bundler been run?"
                    raise FileNotFoundError(msg) from None
                css = (
                    None
                    if not await (path := APath(self.output / bundle_ui.with_suffix(".css"))).exists()
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
