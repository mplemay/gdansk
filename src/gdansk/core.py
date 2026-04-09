from __future__ import annotations

from asyncio import sleep
from asyncio.subprocess import DEVNULL, PIPE, Process, create_subprocess_exec
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from http import HTTPStatus
from json import JSONDecodeError, loads
from os import PathLike
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Final, Literal, cast
from urllib.parse import urlparse, urlunparse

from httpx import AsyncClient
from mcp.server.mcpserver.resources import FunctionResource
from mcp.server.mcpserver.tools.base import Tool

from gdansk.metadata import Metadata, merge_metadata
from gdansk.render import render_template

if TYPE_CHECKING:
    from mcp.server import MCPServer
    from mcp.types import Icon, ToolAnnotations

type PathType = str | PathLike[str]
type RuntimeMode = Literal["development", "production"]

VITE_VERSION: Final[str] = "8.0.3"


@dataclass(slots=True, kw_only=True, frozen=True)
class RuntimeWidget:
    client_path: str


@dataclass(slots=True, kw_only=True, frozen=True)
class FrontendRuntime:
    asset_origin: str
    mode: RuntimeMode
    ssr_endpoint: str
    ssr_origin: str
    vite_origin: str | None
    widgets: dict[str, RuntimeWidget]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> FrontendRuntime:
        widgets_payload = payload.get("widgets")
        if not isinstance(widgets_payload, Mapping):
            msg = 'Frontend runtime metadata is missing a valid "widgets" mapping'
            raise TypeError(msg)

        widgets = {
            str(key): RuntimeWidget(client_path=_expect_string(value, "clientPath"))
            for key, value in widgets_payload.items()
            if isinstance(value, Mapping)
        }

        return cls(
            asset_origin=_expect_string(payload, "assetOrigin"),
            mode=_expect_mode(payload),
            ssr_endpoint=_expect_string(payload, "ssrEndpoint"),
            ssr_origin=_expect_string(payload, "ssrOrigin"),
            vite_origin=_expect_optional_string(payload, "viteOrigin"),
            widgets=widgets,
        )


@dataclass(slots=True, kw_only=True, frozen=True)
class WidgetSpec:
    key: str
    metadata: Metadata | None
    path: Path
    resource: FunctionResource
    tool: Tool
    uri: str


class Ship:
    def __init__(self, views: PathType, *, metadata: Metadata | None = None, client: AsyncClient | None = None) -> None:
        if not (views := Path(views)).exists():
            msg = f"The views directory (i.e. {views}) does not exist"
            raise FileNotFoundError(msg)

        if not views.is_dir():
            msg = f"The views directory (i.e. {views}) is not a directory"
            raise ValueError(msg)

        self._views: Final[Path] = views.absolute().resolve()
        self._widgets_root: Final[Path] = self._views / "widgets"
        self._runtime_path: Final[Path] = self._views / ".gdansk" / "runtime.json"
        self._metadata: Final[Metadata] = metadata or Metadata()
        self._client: Final[AsyncClient] = client or AsyncClient()

        self._frontend: Process | None = None
        self._runtime: FrontendRuntime | None = None
        self._widget_manager: dict[Path, WidgetSpec] = {}

    @asynccontextmanager
    async def mcp(self, app: MCPServer, *, dev: bool = False) -> AsyncIterator[None]:
        for spec in self._widget_manager.values():
            existing = app._tool_manager._tools.get(spec.tool.name)  # noqa: SLF001
            if existing is not None and existing is not spec.tool:
                msg = f"A tool with the name {spec.tool.name} has already been registered"
                raise ValueError(msg)

            app._tool_manager._tools.setdefault(spec.tool.name, spec.tool)  # noqa: SLF001
            app.add_resource(resource=spec.resource)

        await self._start_frontend(dev=dev)

        try:
            yield None
        finally:
            await self._stop_frontend()

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
        key = _widget_key(posix_path)
        resolved_path = (self._widgets_root / relative_path).resolve()

        if not resolved_path.is_file():
            msg = f"The widget path (i.e. {relative_path}) is not a file"
            raise FileNotFoundError(msg)

        uri = f"ui://{key}"
        tool_meta = {**(meta or {}), "ui": {"resourceUri": uri}}
        merged_metadata = merge_metadata(self._metadata, metadata)

        async def resource_fn() -> str:
            return await self._render_widget_page(relative_path)

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
                fn=resource_fn,
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

    async def _render_widget_page(self, path: Path) -> str:
        spec = self._widget_manager[path]
        runtime = self._require_runtime()
        runtime_widget = runtime.widgets.get(spec.key)

        if runtime_widget is None:
            msg = f'The frontend runtime is missing widget "{spec.key}"'
            raise RuntimeError(msg)

        response = await self._client.post(
            _join_url(runtime.ssr_origin, runtime.ssr_endpoint),
            json={"widget": spec.key},
        )

        if response.status_code != HTTPStatus.OK:
            msg = f'Failed to render widget "{spec.key}": {response.status_code} {response.text}'
            raise RuntimeError(msg)

        payload = response.json()
        if not isinstance(payload, Mapping):
            msg = f'Failed to render widget "{spec.key}": invalid SSR payload'
            raise TypeError(msg)

        head = payload.get("head")
        body = payload.get("body")

        if not isinstance(head, list) or not all(isinstance(fragment, str) for fragment in head):
            msg = f'Failed to render widget "{spec.key}": invalid SSR head payload'
            raise TypeError(msg)

        if not isinstance(body, str):
            msg = f'Failed to render widget "{spec.key}": invalid SSR body payload'
            raise TypeError(msg)

        scripts = [_join_url(runtime.asset_origin, runtime_widget.client_path)]
        if runtime.mode == "development":
            if runtime.vite_origin is None:
                msg = "Development runtime metadata is missing viteOrigin"
                raise RuntimeError(msg)

            scripts.insert(0, _join_url(runtime.vite_origin, "/@vite/client"))

        return render_template(
            "base.html",
            body=body,
            head=head,
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
            *self._deno_command("run", "-A", "--node-modules-dir=auto", f"npm:vite@{VITE_VERSION}", "build"),
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

    async def _start_frontend(self, *, dev: bool) -> None:
        await self._stop_frontend()

        self._runtime_path.unlink(missing_ok=True)

        if dev:
            command = self._deno_command("run", "-A", "--node-modules-dir=auto", f"npm:vite@{VITE_VERSION}", "dev")
        else:
            await self._run_build()
            server_path = self._views / ".gdansk" / "server.js"
            if not server_path.is_file():
                msg = f"Expected a production server entry at {server_path}"
                raise RuntimeError(msg)

            command = self._deno_command("run", "-A", "--node-modules-dir=auto", str(server_path))

        self._frontend = await create_subprocess_exec(
            *command,
            cwd=self._views,
            stdin=DEVNULL,
            stdout=DEVNULL,
            stderr=DEVNULL,
        )
        self._runtime = await self._wait_for_runtime()
        self._validate_runtime()

    async def _stop_frontend(self) -> None:
        self._runtime = None
        self._runtime_path.unlink(missing_ok=True)

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
        if self._frontend is None:
            msg = "The frontend process has not been started"
            raise RuntimeError(msg)

        for _ in range(400):
            if self._runtime_path.is_file():
                try:
                    return FrontendRuntime.from_payload(loads(self._runtime_path.read_text(encoding="utf-8")))
                except (JSONDecodeError, OSError, ValueError):
                    pass

            if self._frontend.returncode is not None:
                msg = (
                    "The frontend process exited before it wrote runtime metadata "
                    f"(exit code {self._frontend.returncode})"
                )
                raise RuntimeError(msg)

            await sleep(0.05)

        msg = f"The frontend runtime did not start in time ({self._runtime_path})"
        raise RuntimeError(msg)

    def _validate_runtime(self) -> None:
        runtime = self._require_runtime()
        missing = sorted(spec.key for spec in self._widget_manager.values() if spec.key not in runtime.widgets)
        if not missing:
            return

        msg = f"Frontend runtime is missing widgets: {', '.join(missing)}"
        raise RuntimeError(msg)

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

    def _deno_command(self, *args: str) -> tuple[str, ...]:
        return ("uv", "run", "deno", *args)


def _expect_mode(payload: Mapping[str, Any]) -> RuntimeMode:
    mode = _expect_string(payload, "mode")
    if mode not in {"development", "production"}:
        msg = f"Frontend runtime metadata has an invalid mode: {mode!r}"
        raise ValueError(msg)

    return cast("RuntimeMode", mode)


def _expect_optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value

    msg = f'Frontend runtime metadata has an invalid "{key}" value'
    raise ValueError(msg)


def _expect_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value

    msg = f'Frontend runtime metadata is missing a valid "{key}" value'
    raise ValueError(msg)


def _join_url(origin: str, path: str) -> str:
    parsed = urlparse(origin)
    normalized_path = path if path.startswith("/") else f"/{path}"
    return urlunparse((parsed.scheme, parsed.netloc, normalized_path, "", "", ""))


def _widget_key(path: PurePosixPath) -> str:
    return PurePosixPath(*path.parts[:-1]).as_posix()
