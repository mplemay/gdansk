from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from functools import partial
from os import PathLike
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Final, Literal
from urllib.parse import urlparse

from mcp.server.mcpserver.resources import FunctionResource
from mcp.server.mcpserver.tools.base import Tool

from gdansk._schema import to_strict_schema
from gdansk.vite import Vite
from gdansk.watch import watch_and_rebuild
from gdansk.widget import WidgetMeta, transform

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from mcp.server import MCPServer
    from mcp.types import Icon, ToolAnnotations


type PathType = str | PathLike[str]


@dataclass(slots=True, kw_only=True, frozen=True)
class WidgetSpec:
    key: str
    resource: FunctionResource
    tool: Tool
    uri: str


class Ship:
    def __init__(
        self,
        *,
        vite: Vite | None = None,
        base_url: str | None = None,
    ) -> None:
        if base_url is not None and urlparse(base_url).hostname is None:
            msg = "The base URL must be an absolute URL with a hostname"
            raise ValueError(msg)

        self._base_url: Final[str | None] = base_url
        self._vite: Final[Vite] = vite or Vite()
        self._widget_manager: dict[Path, WidgetSpec] = {}

        self._active = False
        self._watch_task: asyncio.Task[None] | None = None

    @asynccontextmanager
    async def mcp(self, app: MCPServer, *, watch: bool | None = False) -> AsyncIterator[None]:
        for spec in self._widget_manager.values():
            if (existing := app._tool_manager._tools.get(spec.tool.name)) is not None and existing is not spec.tool:  # noqa: SLF001
                msg = f"A tool with the name {spec.tool.name} has already been registered"
                raise ValueError(msg)

            app._tool_manager._tools.setdefault(spec.tool.name, spec.tool)  # noqa: SLF001
            app.add_resource(resource=spec.resource)

        self._session_begin()
        try:
            await self._prepare_frontend(watch=watch)
            yield None
        finally:
            await self._session_end()

    def _session_begin(self) -> None:
        if self._active:
            msg = "The frontend runtime context is already active"
            raise RuntimeError(msg)

        self._active = True
        self._watch_task = None
        self._vite.clear_manifest()

    async def _prepare_frontend(self, *, watch: bool | None) -> None:
        match watch:
            case True:
                await self._vite.build()
                self._vite.load_manifest()
                self._watch_task = asyncio.create_task(watch_and_rebuild(self._vite))
            case False:
                await self._vite.build()
                self._vite.load_manifest()
            case None:
                self._vite.load_manifest()

    async def _session_end(self) -> None:
        watch_task = self._watch_task
        self._watch_task = None
        if watch_task is not None:
            watch_task.cancel()
            with suppress(asyncio.CancelledError):
                await watch_task
        try:
            await self._vite.stop()
        finally:
            self._vite.clear_manifest()
            self._active = False

    async def render_widget_page(self, *, widget_key: str) -> str:
        return self._vite.require_manifest_widget(widget_key).html

    @staticmethod
    def _normalize_widget_path(path: Path) -> PurePosixPath:
        if path.is_absolute():
            msg = f"The widget path (i.e. {path}) must be a relative path"
            raise ValueError(msg)

        posix = PurePosixPath(path.as_posix())
        if any(part in {"", ".", ".."} for part in posix.parts):
            msg = f"The widget path (i.e. {path}) must not contain traversal segments"
            raise ValueError(msg)

        if posix.name not in {"widget.tsx", "widget.jsx"}:
            msg = f"The widget path (i.e. {path}) must point to a widget.tsx or widget.jsx file"
            raise ValueError(msg)

        return posix

    def widget(  # noqa: PLR0913
        self,
        path: PathType,
        name: str | None = None,
        *,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: WidgetMeta | None = None,
        schema: Literal["default", "strict"] = "default",
        structured_output: bool | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        posix_path = self._normalize_widget_path(Path(path))
        key = PurePosixPath(*posix_path.parts[:-1]).as_posix()
        if not (self._vite.widgets_root / Path(posix_path.as_posix())).resolve().is_file():
            msg = f"The widget path (i.e. {path}) is not a file"
            raise FileNotFoundError(msg)

        uri = f"ui://{key}"
        tm, rm = transform(
            widget=meta or WidgetMeta(),
            extra={
                "uri": uri,
                "base_url": self._base_url,
                "description": description,
            },
        )

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            relative_path = Path(posix_path.as_posix())
            if relative_path in self._widget_manager:
                msg = f"The widget {relative_path} has already been registered"
                raise RuntimeError(msg)

            tool = Tool.from_function(
                fn=fn,
                name=name,
                title=title,
                description=description,
                annotations=annotations,
                icons=icons,
                meta=dict(tm.items()),
                structured_output=structured_output,
            )
            if schema == "strict":
                tool.parameters = to_strict_schema(tool.parameters)
            resource = FunctionResource.from_function(
                fn=partial(self.render_widget_page, widget_key=key),
                uri=uri,
                name=name,
                title=title,
                description=description,
                mime_type="text/html;profile=mcp-app",
                meta=dict(rm.items()),
            )

            self._widget_manager[relative_path] = WidgetSpec(
                key=key,
                resource=resource,
                tool=tool,
                uri=uri,
            )

            return fn

        return decorator
