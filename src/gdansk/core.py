from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import cached_property, partial
from os import PathLike
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlparse

from mcp.server.mcpserver.resources import FunctionResource
from mcp.server.mcpserver.tools.base import Tool
from starlette.staticfiles import StaticFiles

from gdansk.context import ShipContext
from gdansk.metadata import Metadata, merge_metadata
from gdansk.widget import WidgetMeta, transform

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from httpx import AsyncClient
    from mcp.server import MCPServer
    from mcp.types import Icon, ToolAnnotations


type PathType = str | PathLike[str]


@dataclass(slots=True, kw_only=True, frozen=True)
class WidgetSpec:
    key: str
    metadata: Metadata | None
    resource: FunctionResource
    tool: Tool
    uri: str


class Ship:
    def __init__(  # noqa: PLR0913
        self,
        views: PathType,
        *,
        assets: str = "dist",
        widgets_directory: str = "widgets",
        base_url: str | None = None,
        host: str = "127.0.0.1",
        port: int = 13_714,
        metadata: Metadata | None = None,
        client: AsyncClient | None = None,
    ) -> None:
        if not (views := Path(views)).exists():
            msg = f"The views directory (i.e. {views}) does not exist"
            raise FileNotFoundError(msg)

        if not views.is_dir():
            msg = f"The views directory (i.e. {views}) is not a directory"
            raise ValueError(msg)

        host = host.strip()
        if not host:
            msg = "The runtime host must not be empty"
            raise ValueError(msg)

        assets = self._normalize_relative_directory(assets, name="assets")
        widgets_directory = self._normalize_relative_directory(widgets_directory, name="widgets")
        if port <= 0 or port > 65_535:  # noqa: PLR2004
            msg = "The runtime port must be an integer between 1 and 65,535"
            raise ValueError(msg)

        if base_url is not None and urlparse(base_url).hostname is None:
            msg = "The base URL must be an absolute URL with a hostname"
            raise ValueError(msg)

        self._assets_dir: Final[str] = assets
        self._base_url: Final[str | None] = base_url
        self._host: Final[str] = host
        self._port: Final[int] = port
        self._views: Final[Path] = views.absolute().resolve()
        self._widgets_root: Final[Path] = self._views / widgets_directory
        self._metadata: Final[Metadata] = metadata or Metadata()
        self._widget_manager: dict[Path, WidgetSpec] = {}
        self._context: Final[ShipContext] = ShipContext(
            self._views,
            assets=self._assets_dir,
            base_url=self._base_url,
            host=self._host,
            port=self._port,
            client=client,
        )

    @cached_property
    def assets(self) -> StaticFiles:
        return StaticFiles(directory=self._views / self._assets_dir, check_dir=True)

    @asynccontextmanager
    async def mcp(self, app: MCPServer, *, watch: bool | None = False) -> AsyncIterator[None]:
        for spec in self._widget_manager.values():
            existing = app._tool_manager._tools.get(spec.tool.name)  # noqa: SLF001
            if existing is not None and existing is not spec.tool:
                msg = f"A tool with the name {spec.tool.name} has already been registered"
                raise ValueError(msg)

            app._tool_manager._tools.setdefault(spec.tool.name, spec.tool)  # noqa: SLF001
            app.add_resource(resource=spec.resource)

        async with self._context.open(watch=watch):
            yield None

    @staticmethod
    def _normalize_relative_directory(directory: str, *, name: str) -> str:
        cleaned = directory.strip().strip("/")
        if not cleaned:
            msg = f"The {name} directory must not be empty"
            raise ValueError(msg)

        posix = PurePosixPath(cleaned)
        if posix.is_absolute() or any(part in {"", ".", ".."} for part in posix.parts):
            msg = f"The {name} directory (i.e. {directory}) must be a relative path without traversal segments"
            raise ValueError(msg)

        return posix.as_posix()

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
        metadata: Metadata | None = None,
        structured_output: bool | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        if (path := Path(path)).is_absolute():
            msg = f"The widget path (i.e. {path}) must be a relative path"
            raise ValueError(msg)

        posix = PurePosixPath(path.as_posix())
        if any(part in {"", ".", ".."} for part in posix.parts):
            msg = f"The widget path (i.e. {path}) must not contain traversal segments"
            raise ValueError(msg)

        if posix.name not in {"widget.tsx", "widget.jsx"}:
            msg = f"The widget path (i.e. {path}) must point to a widget.tsx or widget.jsx file"
            raise ValueError(msg)

        posix_path = PurePosixPath(path.as_posix())
        key = PurePosixPath(*posix_path.parts[:-1]).as_posix()
        resolved_path = (self._widgets_root / path).resolve()

        if not resolved_path.is_file():
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

        merged_metadata = merge_metadata(self._metadata, metadata)

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            if path in self._widget_manager:
                msg = f"The widget {path} has already been registered"
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
            resource = FunctionResource.from_function(
                fn=partial(self._context.render_widget_page, metadata=merged_metadata, widget_key=key),
                uri=uri,
                name=name,
                title=title,
                description=description,
                mime_type="text/html;profile=mcp-app",
                meta=dict(rm.items()),
            )

            self._widget_manager[path] = WidgetSpec(
                key=key,
                metadata=merged_metadata,
                resource=resource,
                tool=tool,
                uri=uri,
            )

            return fn

        return decorator
