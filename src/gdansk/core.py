from asyncio import create_task
from asyncio.subprocess import DEVNULL, create_subprocess_exec
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from os import PathLike
from pathlib import Path, PurePosixPath
from typing import Any, Final

from deno import find_deno_bin
from mcp.server import MCPServer
from mcp.server.mcpserver.resources import FunctionResource
from mcp.server.mcpserver.tools.base import Tool
from mcp.types import Icon, ToolAnnotations

from gdansk.metadata import Metadata

type PathType = str | PathLike[str]


class Ship:
    def __init__(self, views: PathType, *, metadata: Metadata | None = None) -> None:
        if not (views := Path(views)).exists():
            msg = f"The views directory (i.e. {views}) does not exist"
            raise FileNotFoundError(msg)

        if not views.is_dir():
            msg = f"The views directory (i.e. {views}) is not a directory"
            raise ValueError(msg)

        self._views: Final[Path] = views.absolute().resolve()
        self._metadata: Final[Metadata] = metadata or Metadata()

        self._deno: Final[Path] = Path(find_deno_bin()).resolve().absolute()
        self._registry: dict[Path, str] = {}
        self._widget_manager: dict[Path, tuple[Tool, FunctionResource]] = {}

    @asynccontextmanager
    async def mcp(self, app: MCPServer, *, dev: bool = False) -> AsyncIterator[None]:
        # register the widgets
        for tool, resource in self._widget_manager.values():
            if tool.name in app._tool_manager._tools:  # noqa: SLF001
                msg = f"A tool with the name {tool.name} has already been registred"
                raise ValueError(msg)

            app._tool_manager._tools[tool.name] = tool  # noqa: SLF001
            app.add_resource(resource=resource)

        args = ["run", "vite"]
        args += ["dev"] if dev else ["build"]

        proc = create_subprocess_exec(self._deno, *args, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL)

        # production
        if not dev:
            await (await proc).wait()

            args = ["run", "vite", "..."]
            proc = create_subprocess_exec(self._deno, *args, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL)

        task = await create_task(proc)

        yield None

        task.kill()

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
