from __future__ import annotations

from asyncio import sleep
from asyncio.subprocess import DEVNULL, PIPE, Process, create_subprocess_exec
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from functools import cached_property, partial
from http import HTTPStatus
from os import PathLike, stat_result
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Final, Literal, Never
from urllib.parse import urlparse

from deno import find_deno_bin
from httpx import AsyncClient, RequestError
from mcp.server.mcpserver.resources import FunctionResource
from mcp.server.mcpserver.tools.base import Tool
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.staticfiles import StaticFiles

from gdansk.metadata import Metadata, merge_metadata
from gdansk.render import render_template
from gdansk.utils import join_url, join_url_path
from gdansk.widget import WidgetMeta, transform

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from mcp.server import MCPServer
    from mcp.types import Icon, ToolAnnotations
    from starlette.responses import Response
    from starlette.types import Scope


type PathType = str | PathLike[str]

DEV_CLIENT_PREFIX: Final[str] = "/@gdansk/client"
DEFAULT_ASSETS_DIR: Final[str] = "dist"
DEFAULT_WIDGETS_DIR: Final[str] = "widgets"
HEALTH_ENDPOINT: Final[str] = "/health"
MAX_RUNTIME_PORT: Final[int] = 65535
SSR_ENDPOINT: Final[str] = "/ssr"


class HealthCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["OK"] = "OK"


class GdanskRenderResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    body: str
    head: list[str]


@dataclass(slots=True, kw_only=True, frozen=True)
class WidgetSpec:
    key: str
    metadata: Metadata | None
    resource: FunctionResource
    tool: Tool
    uri: str


class AssetFiles(StaticFiles):
    def file_response(
        self,
        full_path: PathType,
        stat_result: stat_result,
        scope: Scope,
        status_code: int = HTTPStatus.OK,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response


class ShipContext:
    def __init__(  # noqa: PLR0913
        self,
        views: Path,
        *,
        assets: str,
        base_url: str | None = None,
        host: str,
        port: int,
        client: AsyncClient | None = None,
    ) -> None:
        self._assets_dir: Final[str] = assets
        self._base_url: Final[str | None] = base_url
        self._client: Final[AsyncClient] = client or AsyncClient()
        self._deno: Final[str] = find_deno_bin()
        self._host: Final[str] = host
        self._port: Final[int] = port
        self._views: Final[Path] = views

        self._active = False
        self._dev = False
        self._frontend: Process | None = None
        self._runtime_origin: str | None = None

    @asynccontextmanager
    async def open(self, *, dev: bool) -> AsyncIterator[None]:
        if self._active:
            msg = "The frontend runtime context is already active"
            raise RuntimeError(msg)

        self._active = True
        try:
            await self._start(dev=dev)
            try:
                yield None
            finally:
                await self._stop()
        finally:
            self._active = False

    async def render_widget_page(self, *, metadata: Metadata | None, widget_key: str) -> str:
        if self._dev:
            runtime_origin = self._require_runtime_origin()
            rendered = await self._render_with_ssr_server(runtime_origin=runtime_origin, widget_key=widget_key)
            scripts = [
                join_url(runtime_origin, "/@vite/client"),
                join_url(runtime_origin, self._development_asset_path(widget_key=widget_key)),
            ]
            body = rendered.body
            head = rendered.head
        else:
            rendered = await self._render_with_ssr_server(
                runtime_origin=self._require_runtime_origin(),
                widget_key=widget_key,
            )
            scripts = [self._production_asset_url(widget_key=widget_key)]
            body = rendered.body
            head = rendered.head
            runtime_origin = None

        return render_template(
            "base.html",
            body=body,
            dev=self._dev,
            head=head,
            metadata=metadata,
            runtime_origin=runtime_origin,
            scripts=scripts,
        )

    def _require_runtime_origin(self) -> str:
        if self._runtime_origin is None:
            msg = "The frontend runtime is not running"
            raise RuntimeError(msg)

        return self._runtime_origin

    def _asset_base_url(self) -> str | None:
        if self._base_url is None:
            return None

        return join_url_path(self._base_url, self._assets_dir)

    def _asset_url(self, path: str) -> str:
        normalized = path.lstrip("/")
        if (asset_base_url := self._asset_base_url()) is not None:
            return join_url_path(asset_base_url, normalized)

        return PurePosixPath("/", self._assets_dir, normalized).as_posix()

    def _production_asset_url(self, *, widget_key: str) -> str:
        return self._asset_url(f"{widget_key}/client.js")

    @staticmethod
    def _development_asset_path(*, widget_key: str) -> str:
        return PurePosixPath(DEV_CLIENT_PREFIX, f"{widget_key}.tsx").as_posix()

    async def _render_with_ssr_server(self, *, runtime_origin: str, widget_key: str) -> GdanskRenderResponse:
        payload = {"widget": widget_key}
        if (asset_base_url := self._asset_base_url()) is not None:
            payload["assetBaseUrl"] = asset_base_url

        response = await self._client.post(
            join_url(runtime_origin, SSR_ENDPOINT),
            json=payload,
        )

        if response.status_code != HTTPStatus.OK:
            msg = f'Failed to render widget "{widget_key}": {response.status_code} {response.text}'
            raise RuntimeError(msg)

        try:
            return GdanskRenderResponse.model_validate_json(response.text)
        except ValidationError as e:
            msg = f'Failed to render widget "{widget_key}": invalid SSR payload'
            raise TypeError(msg) from e

    @staticmethod
    def _raise_runtime_error(message: str) -> Never:
        raise RuntimeError(message)

    async def _run_build(self) -> None:
        proc = await create_subprocess_exec(
            self._deno,
            "run",
            "-A",
            "--node-modules-dir=auto",
            "npm:vite",
            "build",
            cwd=self._views,
            stdin=DEVNULL,
            stdout=PIPE,
            stderr=PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            return

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        output = "\n".join(part for part in (stdout_text, stderr_text) if part)
        msg = "Failed to build the frontend"
        if output:
            msg = f"{msg}:\n{output}"
        raise RuntimeError(msg)

    async def _start(self, *, dev: bool) -> None:
        if self._frontend is not None or self._runtime_origin is not None:
            msg = "The frontend runtime context is already active"
            raise RuntimeError(msg)

        self._dev = dev
        self._runtime_origin = f"http://{self._host}:{self._port}"

        try:
            if dev:
                command = (
                    self._deno,
                    "run",
                    "-A",
                    "--node-modules-dir=auto",
                    "npm:vite",
                    "dev",
                    "--host",
                    self._host,
                    "--port",
                    str(self._port),
                    "--strictPort",
                )
            else:
                await self._run_build()
                server_path = self._views / self._assets_dir / "server.js"
                if not server_path.is_file():
                    msg = f"The frontend build did not produce a production server entry at {server_path}"
                    self._raise_runtime_error(msg)

                command = (self._deno, "run", "-A", "--node-modules-dir=auto", str(server_path))

            self._frontend = await create_subprocess_exec(
                *command,
                cwd=self._views,
                stdin=DEVNULL,
                stdout=DEVNULL,
                stderr=DEVNULL,
            )
            await self._wait_for_health()
        except Exception:
            await self._stop()
            raise

    async def _stop(self) -> None:
        self._dev = False
        self._runtime_origin = None

        frontend = self._frontend
        self._frontend = None

        if frontend is None:
            return

        if frontend.returncode is None:
            with suppress(ProcessLookupError):
                frontend.terminate()

            for _ in range(20):
                if frontend.returncode is not None:
                    break
                await sleep(0.05)

            if frontend.returncode is None:
                with suppress(ProcessLookupError):
                    frontend.kill()
                await frontend.wait()

    async def _wait_for_health(self) -> None:
        if self._frontend is None or self._runtime_origin is None:
            msg = "The frontend process has not been started"
            raise RuntimeError(msg)

        health_url = join_url(self._runtime_origin, HEALTH_ENDPOINT)

        for _ in range(1200):
            if self._frontend.returncode is not None:
                msg = (
                    "The frontend process exited before the health endpoint became available "
                    f"(exit code {self._frontend.returncode})"
                )
                raise RuntimeError(msg)

            try:
                response = await self._client.get(health_url, timeout=0.2)
            except RequestError:
                pass
            else:
                if response.status_code == HTTPStatus.OK:
                    try:
                        health = HealthCheck.model_validate(response.json())
                    except (TypeError, ValueError):
                        pass
                    else:
                        if health.status == "OK":
                            return

            await sleep(0.05)

        msg = (
            f"The frontend runtime did not start in time ({health_url}). "
            f'Ensure Ship(host="{self._host}", port={self._port}) matches '
            f'gdansk({{ host: "{self._host}", port: {self._port} }}).'
        )
        raise RuntimeError(msg)


class Ship:
    def __init__(  # noqa: PLR0913
        self,
        views: PathType,
        *,
        assets: str = DEFAULT_ASSETS_DIR,
        widgets_directory: str = DEFAULT_WIDGETS_DIR,
        base_url: str | None = None,
        host: str = "127.0.0.1",
        port: int = 13714,
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
        if port <= 0 or port > MAX_RUNTIME_PORT:
            msg = f"The runtime port must be an integer between 1 and {MAX_RUNTIME_PORT}"
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
        return AssetFiles(directory=self._views / self._assets_dir, check_dir=False)

    @asynccontextmanager
    async def mcp(self, app: MCPServer, *, dev: bool = False) -> AsyncIterator[None]:
        for spec in self._widget_manager.values():
            existing = app._tool_manager._tools.get(spec.tool.name)  # noqa: SLF001
            if existing is not None and existing is not spec.tool:
                msg = f"A tool with the name {spec.tool.name} has already been registered"
                raise ValueError(msg)

            app._tool_manager._tools.setdefault(spec.tool.name, spec.tool)  # noqa: SLF001
            app.add_resource(resource=spec.resource)

        async with self._context.open(dev=dev):
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
        relative_path = Path(path)
        self._validate_widget_path(relative_path)

        posix_path = PurePosixPath(relative_path.as_posix())
        key = PurePosixPath(*posix_path.parts[:-1]).as_posix()
        resolved_path = (self._widgets_root / relative_path).resolve()

        if not resolved_path.is_file():
            msg = f"The widget path (i.e. {relative_path}) is not a file"
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
            resource = FunctionResource.from_function(
                fn=partial(self._context.render_widget_page, metadata=merged_metadata, widget_key=key),
                uri=uri,
                name=name,
                title=title,
                description=description,
                mime_type="text/html;profile=mcp-app",
                meta=dict(rm.items()),
            )

            self._widget_manager[relative_path] = WidgetSpec(
                key=key,
                metadata=merged_metadata,
                resource=resource,
                tool=tool,
                uri=uri,
            )

            return fn

        return decorator

    def _validate_widget_path(self, path: Path) -> None:
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
