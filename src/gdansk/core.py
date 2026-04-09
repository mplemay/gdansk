from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from os import PathLike
from pathlib import Path, PurePosixPath
from typing import Any, Final

from mcp.server import MCPServer
from mcp.server.mcpserver.resources import FunctionResource
from mcp.server.mcpserver.tools.base import Tool
from mcp.types import Icon, ToolAnnotations

from gdansk.metadata import Metadata

type PathType = str | PathLike[str]


class Ship:
    def __init__(self, views: PathType, *, metadata: Metadata | None = None, ssr: bool = False) -> None:
        if not (views := Path(views)).exists():
            msg = f"The views directory (i.e. {views}) does not exist"
            raise FileNotFoundError(msg)

        if not views.is_dir():
            msg = f"The views directory (i.e. {views}) is not a directory"
            raise ValueError(msg)

        self._views: Final[Path] = views.absolute().resolve()
        self._metadata: Final[Metadata] = metadata or Metadata()
        self._ssr: Final[bool] = ssr

        self._registry: dict[Path, str] = {}
        self._widget_manager: dict[Path, tuple[Tool, FunctionResource]] = {}

    @asynccontextmanager
    async def mcp(self, app: MCPServer, *, dev: bool = False) -> AsyncIterator[None]:  # noqa: ARG002
        # register the widgets
        for tool, resource in self._widget_manager.values():
            if tool.name in app._tool_manager._tools:  # noqa: SLF001
                msg = f"A tool with the name {tool.name} has already been registred"
                raise ValueError(msg)

            app._tool_manager._tools[tool.name] = tool  # noqa: SLF001
            app.add_resource(resource=resource)

        yield

    def widget(  # noqa: PLR0913
        self,
        path: PathType,
        name: str | None = None,
        *,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: dict[str, Any] | None = None,
        metadata: Metadata | None = None,  # noqa: ARG002
        ssr: bool | None = None,
        structured_output: bool | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        if (path := Path(path)).is_file():
            msg = f"The widget path (i.e. {path}) is not a file"
            raise FileNotFoundError(msg)

        if path.is_absolute():
            msg = f"The widget path (i.e. {path}) must be a relative path"
            raise ValueError(msg)

        posix = PurePosixPath(path.as_posix())
        if any(part in {"", ".", ".."} for part in posix.parts):
            msg = f"The widget path (i.e. {path}) must not contain traversal segments"
            raise ValueError(msg)

        if path.suffix not in {".tsx", ".jsx"}:
            msg = f"The widget path (i.e. {path}) must be a .tsx or .jsx file"
            raise ValueError(msg)

        ssr = self._ssr or ssr
        uri = f"ui://{PurePosixPath(*posix.parts[:-1])}"
        meta = meta or {}
        meta["ui"] = {"resourceUri": uri}

        def resource_fn() -> str | None:
            return self._registry.get(path)

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            if path in self._widget_manager:
                msg = f"The widget {path} has already been registered"
                raise RuntimeError(msg)

            self._widget_manager[path] = (
                Tool.from_function(
                    fn=fn,
                    name=name,
                    title=title,
                    description=description,
                    annotations=annotations,
                    icons=icons,
                    meta=meta,
                    structured_output=structured_output,
                ),
                FunctionResource.from_function(
                    fn=resource_fn,
                    uri=uri,
                    name=name,
                    title=title,
                    description=description,
                    mime_type="text/html;profile=mcp-app",
                ),
            )

            return fn

        return decorator
