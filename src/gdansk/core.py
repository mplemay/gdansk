from asyncio import create_subprocess_exec
from asyncio.subprocess import PIPE
from collections.abc import Callable
from os import PathLike
from pathlib import Path, PurePosixPath
from typing import Any, Final

from asyncer import syncify
from deno import find_deno_bin
from mcp.server import MCPServer
from mcp.server.streamable_http import EventStore
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Icon, ToolAnnotations
from starlette.applications import Starlette

from gdansk.metadata import Metadata

type PathType = str | PathLike[str]


class Ship:
    def __init__(self, mcp: MCPServer, views: PathType, *, metadata: Metadata | None = None, ssr: bool = False) -> None:
        if not (views := Path(views)).exists():
            msg = f"The views directory (i.e. {views}) does not exist"
            raise FileNotFoundError(msg)

        if not views.is_dir():
            msg = f"The views directory (i.e. {views}) is not a directory"
            raise ValueError(msg)

        self._mcp: Final[MCPServer] = mcp
        self._views: Final[Path] = views.absolute().resolve()
        self._metadata: Final[Metadata] = metadata or Metadata()
        self._ssr: Final[bool] = ssr

        self._registry: dict[Path, str] = {}

    async def build(self, *, dev: bool = False) -> None:
        deno = find_deno_bin()
        mode = "dev" if dev else "build"

        proc = await create_subprocess_exec(
            deno,
            "run",
            "vite",
            mode,
            stdout=PIPE,
            stdin=PIPE,
        )

        await proc.wait()

    def __call__(
        self,
        *,
        streamable_http_path: str = "/mcp",
        json_response: bool = False,
        stateless_http: bool = False,
        event_store: EventStore | None = None,
        retry_interval: int | None = None,
        transport_security: TransportSecuritySettings | None = None,
        host: str = "127.0.0.1",
        dev: bool = False,
    ) -> Starlette:
        app = self._mcp.streamable_http_app(
            streamable_http_path=streamable_http_path,
            json_response=json_response,
            stateless_http=stateless_http,
            event_store=event_store,
            retry_interval=retry_interval,
            transport_security=transport_security,
            host=host,
        )

        # run the build asynchronously (and possibly in the background)
        syncify(self.build)(dev=dev)

        return app

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

        if any(part in {"", ".", ".."} for part in (posix := PurePosixPath(path.as_posix())).parts):
            msg = f"The widget path (i.e. {path}) must not contain traversal segments"
            raise ValueError(msg)

        if path.suffix not in {".tsx", ".jsx"}:
            msg = f"The widget path (i.e. {path}) must be a .tsx or .jsx file"
            raise ValueError(msg)

        ssr = self._ssr or ssr
        uri = f"ui://{PurePosixPath(*posix.parts[:-1])}"
        meta = meta or {}
        meta["ui"] = {"resourceUri": uri}

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._mcp.tool(
                name=name,
                title=title,
                description=description,
                annotations=annotations,
                icons=icons,
                meta=meta,
                structured_output=structured_output,
            )(fn)

            @self._mcp.resource(
                uri=uri,
                name=name,
                title=title,
                description=description,
                mime_type="text/html;profile=mcp-app",
            )
            def _() -> str | None:
                return self._registry.get(path)

            return fn

        return decorator
