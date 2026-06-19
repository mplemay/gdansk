from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from os import PathLike
from pathlib import Path, PurePosixPath
from re import IGNORECASE, Pattern, compile as compile_pattern
from typing import TYPE_CHECKING, Any, Final, Literal
from urllib.parse import urlparse

from httpx import AsyncClient

from gdansk._mcp import FunctionResource, Tool
from gdansk._schema import to_strict_schema
from gdansk.metadata import Metadata, merge_metadata
from gdansk.render import render_template
from gdansk.utils import join_url
from gdansk.vite import Vite
from gdansk.widget import WidgetMeta, transform

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from mcp.types import Icon, ToolAnnotations

    from gdansk._mcp import MCPServer


type PathType = str | PathLike[str]

INLINE_SCRIPT_END_TAG_PATTERN: Final[Pattern[str]] = compile_pattern(r"</script", IGNORECASE)
INLINE_STYLE_END_TAG_PATTERN: Final[Pattern[str]] = compile_pattern(r"</style", IGNORECASE)


@dataclass(slots=True, kw_only=True, frozen=True)
class WidgetSpec:
    key: str
    metadata: Metadata | None
    resource: FunctionResource
    tool: Tool
    uri: str


class Ship:
    def __init__(
        self,
        *,
        vite: Vite | None = None,
        base_url: str | None = None,
        metadata: Metadata | None = None,
        client: AsyncClient | None = None,
    ) -> None:
        if base_url is not None and urlparse(base_url).hostname is None:
            msg = "The base URL must be an absolute URL with a hostname"
            raise ValueError(msg)

        self._base_url: Final[str | None] = base_url
        self._client: Final[AsyncClient | None] = client
        self._dev = False
        self._metadata: Final[Metadata] = metadata or Metadata()
        self._session_client: AsyncClient | None = None
        self._vite: Final[Vite] = vite or Vite()
        self._widget_manager: dict[Path, WidgetSpec] = {}

        self._active = False

    @asynccontextmanager
    async def mcp(self, app: MCPServer, *, watch: bool | None = False) -> AsyncIterator[None]:
        for spec in self._widget_manager.values():
            existing = app._tool_manager._tools.get(spec.tool.name)  # noqa: SLF001
            if existing is not None and existing is not spec.tool:
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
        self._dev = False
        self._vite.clear_manifest()

    async def _prepare_frontend(self, *, watch: bool | None) -> None:
        match watch:
            case True:
                await self._vite.start_dev()
                await self._vite.wait_until_ready(await self._require_client())
                self._dev = True
            case False:
                await self._vite.build()
                self._vite.load_manifest()
            case None:
                self._vite.load_manifest()

    async def _require_client(self) -> AsyncClient:
        if self._client is not None:
            return self._client

        if self._session_client is None:
            self._session_client = AsyncClient()

        return self._session_client

    async def _session_end(self) -> None:
        try:
            await self._vite.stop()
        finally:
            self._vite.clear_manifest()
            self._dev = False
            self._active = False
            if self._session_client is not None:
                await self._session_client.aclose()
                self._session_client = None

    async def render_widget_page(self, *, metadata: Metadata | None, widget_key: str) -> str:
        body = ""
        head: list[str] = []
        inline_scripts: list[str] = []
        runtime_origin: str | None = None

        if self._dev:
            runtime_origin = self._vite.require_origin()
            scripts = [
                join_url(runtime_origin, "/@vite/client"),
                join_url(runtime_origin, self._vite.development_asset_path(widget_key=widget_key)),
            ]
        else:
            widget = self._vite.require_manifest_widget(widget_key)
            scripts = []
            head = [f"<style>{_escape_inline_style(style)}</style>" for style in widget.inline.styles]
            inline_scripts = [_escape_inline_script(widget.inline.script)]

        return render_template(
            "base.html",
            body=body,
            dev=self._dev,
            head=head,
            inline_scripts=inline_scripts,
            metadata=metadata,
            runtime_origin=runtime_origin,
            scripts=scripts,
        )

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
        metadata: Metadata | None = None,
        schema: Literal["default", "strict"] = "default",
        structured_output: bool | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        posix_path = self._normalize_widget_path(Path(path))
        key = PurePosixPath(*posix_path.parts[:-1]).as_posix()
        resolved_path = (self._vite.widgets_root / Path(posix_path.as_posix())).resolve()

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
                fn=partial(self.render_widget_page, metadata=merged_metadata, widget_key=key),
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


def _escape_inline_closing_tag(value: str, pattern: Pattern[str], replacement: str) -> str:
    return pattern.sub(replacement, value)


def _escape_inline_script(value: str) -> str:
    return _escape_inline_closing_tag(value, INLINE_SCRIPT_END_TAG_PATTERN, "<\\/script")


def _escape_inline_style(value: str) -> str:
    return _escape_inline_closing_tag(value, INLINE_STYLE_END_TAG_PATTERN, "<\\/style")
