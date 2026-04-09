from __future__ import annotations

from asyncio import sleep
from asyncio.subprocess import DEVNULL, PIPE, Process, create_subprocess_exec
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from http import HTTPStatus
from os import PathLike
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Final, Literal

from httpx import AsyncClient, RequestError
from mcp.server.mcpserver.resources import FunctionResource
from mcp.server.mcpserver.tools.base import Tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from gdansk.metadata import Metadata, merge_metadata
from gdansk.render import render_template
from gdansk.utils import join_url

if TYPE_CHECKING:
    from mcp.server import MCPServer
    from mcp.types import Icon, ToolAnnotations

type PathType = str | PathLike[str]
type RuntimeMode = Literal["development", "production"]

RUNTIME_ENDPOINT: Final[str] = "/__gdansk_runtime"


class RuntimeWidget(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    client_path: str = Field(alias="clientPath")


class FrontendRuntime(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    asset_origin: str = Field(alias="assetOrigin")
    mode: RuntimeMode
    ssr_endpoint: str = Field(alias="ssrEndpoint")
    ssr_origin: str = Field(alias="ssrOrigin")
    vite_origin: str | None = Field(alias="viteOrigin")
    widgets: dict[str, RuntimeWidget]

    @model_validator(mode="before")
    @classmethod
    def normalize_widgets(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        widgets_payload = normalized.get("widgets")
        if widgets_payload is None:
            return normalized
        if not isinstance(widgets_payload, Mapping):
            msg = 'Frontend runtime metadata is missing a valid "widgets" mapping'
            raise TypeError(msg)
        normalized["widgets"] = {
            str(key): value for key, value in widgets_payload.items() if isinstance(value, (BaseModel, Mapping))
        }
        return normalized


class GdanskRenderResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    body: str
    head: list[str]


@dataclass(slots=True, kw_only=True, frozen=True)
class WidgetSpec:
    key: str
    metadata: Metadata | None
    path: Path
    resource: FunctionResource
    tool: Tool
    uri: str


class ShipContext:
    def __init__(
        self,
        views: Path,
        *,
        host: str,
        port: int,
        widget_manager: Mapping[Path, WidgetSpec],
        client: AsyncClient | None = None,
    ) -> None:
        self._client: Final[AsyncClient] = client or AsyncClient()
        self._host: Final[str] = host
        self._port: Final[int] = port
        self._views: Final[Path] = views
        self._widget_manager: Final[Mapping[Path, WidgetSpec]] = widget_manager
        self._runtime_path: Final[Path] = self._views / "dist" / "runtime.json"

        self._active = False
        self._frontend: Process | None = None
        self._runtime: FrontendRuntime | None = None
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

    async def render_widget_page(self, *, path: Path) -> str:
        spec = self._widget_manager[path]
        runtime = self._require_runtime()
        runtime_widget = runtime.widgets.get(spec.key)

        if runtime_widget is None:
            msg = f'The frontend runtime is missing widget "{spec.key}"'
            raise RuntimeError(msg)

        response = await self._client.post(
            join_url(runtime.ssr_origin, runtime.ssr_endpoint),
            json={"widget": spec.key},
        )

        if response.status_code != HTTPStatus.OK:
            msg = f'Failed to render widget "{spec.key}": {response.status_code} {response.text}'
            raise RuntimeError(msg)

        try:
            rendered = GdanskRenderResponse.model_validate_json(response.text)
        except ValidationError as e:
            msg = f'Failed to render widget "{spec.key}": invalid SSR payload'
            raise TypeError(msg) from e

        scripts = [join_url(runtime.asset_origin, runtime_widget.client_path)]
        if runtime.mode == "development":
            if runtime.vite_origin is None:
                msg = "Development runtime metadata is missing viteOrigin"
                raise RuntimeError(msg)

            scripts.insert(0, join_url(runtime.vite_origin, "/@vite/client"))

        return render_template(
            "base.html",
            body=rendered.body,
            head=rendered.head,
            metadata=spec.metadata,
            scripts=scripts,
        )

    def _require_runtime(self) -> FrontendRuntime:
        if self._runtime is None:
            msg = "The frontend runtime is not running"
            raise RuntimeError(msg)

        return self._runtime

    async def _run_build(self) -> None:
        proc = await create_subprocess_exec(
            *self._deno_command("run", "-A", "--node-modules-dir=auto", "npm:vite", "build"),
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
        if self._frontend is not None or self._runtime is not None or self._runtime_origin is not None:
            msg = "The frontend runtime context is already active"
            raise RuntimeError(msg)

        self._runtime_path.unlink(missing_ok=True)
        self._runtime_origin = f"http://{self._host}:{self._port}"

        if dev:
            command = self._deno_command("run", "-A", "--node-modules-dir=auto", "npm:vite", "dev")
        else:
            await self._run_build()
            server_path = self._views / "dist" / "server.js"
            if not server_path.is_file():
                msg = f"Expected a production server entry at {server_path}"
                raise RuntimeError(msg)

            command = self._deno_command("run", "-A", "--node-modules-dir=auto", str(server_path))

        try:
            self._frontend = await create_subprocess_exec(
                *command,
                cwd=self._views,
                stdin=DEVNULL,
                stdout=DEVNULL,
                stderr=DEVNULL,
            )
            self._runtime = await self._wait_for_runtime()
            self._validate_runtime()
        except Exception:
            await self._stop()
            raise

    async def _stop(self) -> None:
        self._runtime = None
        self._runtime_path.unlink(missing_ok=True)
        self._runtime_origin = None

        if self._frontend is None:
            return

        self._frontend.terminate()
        for _ in range(20):
            if self._frontend.returncode is not None:
                break
            await sleep(0.05)

        if self._frontend.returncode is None:
            self._frontend.kill()
            await self._frontend.wait()

        self._frontend = None

    async def _wait_for_runtime(self) -> FrontendRuntime:
        if self._frontend is None or self._runtime_origin is None:
            msg = "The frontend process has not been started"
            raise RuntimeError(msg)

        runtime_url = join_url(self._runtime_origin, RUNTIME_ENDPOINT)

        for _ in range(1200):
            if self._frontend.returncode is not None:
                msg = (
                    "The frontend process exited before the runtime endpoint became available "
                    f"(exit code {self._frontend.returncode})"
                )
                raise RuntimeError(msg)

            try:
                response = await self._client.get(runtime_url, timeout=0.2)
            except RequestError:
                pass
            else:
                if response.status_code == HTTPStatus.OK:
                    try:
                        return FrontendRuntime.model_validate(response.json())
                    except (TypeError, ValueError):
                        pass

            await sleep(0.05)

        msg = (
            f"The frontend runtime did not start in time ({runtime_url}). "
            f'Ensure Ship(host="{self._host}", port={self._port}) matches '
            f'gdansk({{ host: "{self._host}", port: {self._port} }}).'
        )
        raise RuntimeError(msg)

    def _validate_runtime(self) -> None:
        runtime = self._require_runtime()
        missing = sorted(spec.key for spec in self._widget_manager.values() if spec.key not in runtime.widgets)
        if not missing:
            return

        msg = f"Frontend runtime is missing widgets: {', '.join(missing)}"
        raise RuntimeError(msg)

    def _deno_command(self, *args: str) -> tuple[str, ...]:
        return ("uv", "run", "deno", *args)


class Ship:
    def __init__(
        self,
        views: PathType,
        *,
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

        if port <= 0 or port > 65535:  # noqa: PLR2004
            msg = "The runtime port must be an integer between 1 and 65535"
            raise ValueError(msg)

        self._host: Final[str] = host
        self._port: Final[int] = port
        self._views: Final[Path] = views.absolute().resolve()
        self._widgets_root: Final[Path] = self._views / "widgets"
        self._metadata: Final[Metadata] = metadata or Metadata()
        self._widget_manager: dict[Path, WidgetSpec] = {}
        self._context: Final[ShipContext] = ShipContext(
            self._views,
            host=self._host,
            port=self._port,
            widget_manager=self._widget_manager,
            client=client,
        )

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
        tool_meta = {**(meta or {}), "ui": {"resourceUri": uri}}
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
                meta=tool_meta,
                structured_output=structured_output,
            )
            resource = FunctionResource.from_function(
                fn=partial(self._context.render_widget_page, path=relative_path),
                uri=uri,
                name=name,
                title=title,
                description=description,
                mime_type="text/html;profile=mcp-app",
            )

            self._widget_manager[relative_path] = WidgetSpec(
                key=key,
                metadata=merged_metadata,
                path=relative_path,
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
