"""Core integration between FastMCP tools and gdansk widget resources."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, ClassVar

from anyio import Path as APath

from gdansk._core import LightningCSS, Page, VitePlugin, bundle, run
from gdansk.metadata import Metadata, merge_metadata
from gdansk.render import ENV

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Sequence
    from os import PathLike

    from mcp.server import MCPServer as FastMCP
    from mcp.types import Icon, ToolAnnotations
    from starlette.applications import Starlette

    from gdansk.protocol import Plugin

logger = logging.getLogger(__name__)


def _validate_plugins(plugins: Sequence[Plugin] | None) -> None:
    if plugins is None:
        return

    for plugin in plugins:
        if isinstance(plugin, (LightningCSS, VitePlugin)):
            continue

        msg = "Amber plugins must be LightningCSS or VitePlugin instances"
        raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class Amber:
    """Registers widget-backed MCP tools and serves their bundled assets."""

    _widgets: set[Page] = field(default_factory=set, init=False)
    _template: ClassVar[str] = "template.html"
    _page_min_parts: ClassVar[int] = 2

    mcp: FastMCP
    views: Path
    output: Path = field(init=False)
    ssr: bool = field(default=False, kw_only=True)
    cache_html: bool = field(default=True, kw_only=True)
    metadata: Metadata | None = field(default=None, kw_only=True)
    plugins: Sequence[Plugin] | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        """Validate required paths and initialize derived output paths."""
        if not self.views.is_dir():
            msg = f"The views directory {self.views} does not exist"
            raise ValueError(msg)

        _validate_plugins(self.plugins)
        object.__setattr__(self, "output", self.views / ".gdansk")

    async def _run_build_pipeline(self, *, dev: bool) -> None:
        pages = sorted(self._widgets, key=lambda page: page.path.as_posix())
        await bundle(
            pages=pages,
            dev=dev,
            minify=not dev,
            output=self.output,
            cwd=self.views,
            plugins=self.plugins,
        )

    @staticmethod
    def _log_background_task_error(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        logger.exception("Amber background task failed", exc_info=exc)

    @staticmethod
    async def _shutdown_dev_tasks(
        *,
        bundle_task: asyncio.Task[None] | None,
    ) -> None:
        tasks = [candidate for candidate in [bundle_task] if candidate is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _normalize_widget_input(widget: str | PathLike[str]) -> Path:
        widget_path = Path(widget)
        if widget_path.is_absolute():
            msg = f"The widget path (i.e. {widget}) must be a relative path"
            raise ValueError(msg)

        widget_posix = PurePosixPath(widget_path.as_posix())
        if any(part in {"", ".", ".."} for part in widget_posix.parts):
            msg = f"The widget path (i.e. {widget}) must not contain traversal segments"
            raise ValueError(msg)

        if widget_posix.parts and widget_posix.parts[0] == "widgets":
            msg = f"The widget path (i.e. {widget}) must not start with widgets/"
            raise ValueError(msg)

        return Path(*widget_posix.parts)

    @staticmethod
    def _resolve_widget_path_candidates(widget: Path) -> tuple[Path, ...]:
        if widget.suffix:
            if widget.suffix not in {".tsx", ".jsx"}:
                msg = f"The widget path (i.e. {widget}) must be a .tsx or .jsx file"
                raise ValueError(msg)
            if widget.name not in {"widget.tsx", "widget.jsx"}:
                msg = (
                    f"The widget path (i.e. {widget}) must match **/widget.tsx or **/widget.jsx "
                    "and must not start with widgets/"
                )
                raise ValueError(msg)
            return (widget,)

        return (widget / "widget.tsx", widget / "widget.jsx")

    @staticmethod
    def _normalize_widget_path_and_uri(widget: Path) -> tuple[Path, Path, str]:
        widget_posix = PurePosixPath(widget.as_posix())

        if (
            len(widget_posix.parts) < Amber._page_min_parts
            or widget_posix.parts[0] == "widgets"
            or widget_posix.name not in {"widget.tsx", "widget.jsx"}
        ):
            msg = (
                f"The widget path (i.e. {widget}) must match **/widget.tsx or **/widget.jsx "
                "and must not start with widgets/"
            )
            raise ValueError(msg)

        normalized_widget = Path(*widget_posix.parts)
        bundle_page = Path("widgets", *widget_posix.parts)
        uri = f"ui://{PurePosixPath(*widget_posix.parts[:-1])}"
        return normalized_widget, bundle_page, uri

    def __call__(self, *, dev: bool = False) -> Starlette:
        """Build and return the Starlette app that serves registered resources."""
        app = self.mcp.streamable_http_app()
        if not self._widgets:
            return app

        bundle_task: asyncio.Task[None] | None = None
        original_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def _lifespan(starlette_app: Starlette) -> AsyncIterator[None]:
            if dev:
                nonlocal bundle_task
                bundle_task = asyncio.create_task(self._run_build_pipeline(dev=True))
                bundle_task.add_done_callback(self._log_background_task_error)
            else:
                await self._run_build_pipeline(dev=False)

            async with original_lifespan(starlette_app):
                try:
                    yield
                finally:
                    if dev:
                        await Amber._shutdown_dev_tasks(bundle_task=bundle_task)

        app.router.lifespan_context = _lifespan
        return app

    def tool(  # noqa: C901, PLR0913, PLR0915
        self,
        widget: str | PathLike[str],
        name: str | None = None,
        *,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: dict[str, Any] | None = None,
        metadata: Metadata | None = None,
        ssr: bool | None = None,
        structured_output: bool | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register a tool and bind its widget resource into the MCP server."""
        widget_path = self._normalize_widget_input(widget)
        widget_candidates = self._resolve_widget_path_candidates(widget_path)

        bundle_page: Path | None = None
        uri: str | None = None

        for widget_candidate in widget_candidates:
            _, candidate_bundle_page, candidate_uri = self._normalize_widget_path_and_uri(widget_candidate)
            if (self.views / candidate_bundle_page).is_file():
                bundle_page = candidate_bundle_page
                uri = candidate_uri
                break

        if bundle_page is None or uri is None:
            if len(widget_candidates) == 1:
                msg = f"The widget path (i.e. {widget_path}) was not found"
            else:
                msg = (
                    f"The widget path (i.e. {widget_path}) was not found. "
                    f"Expected one of: {widget_candidates[0]}, {widget_candidates[1]}"
                )
            raise FileNotFoundError(msg)

        ssr = self.ssr if ssr is None else ssr
        page_spec = Page(path=bundle_page, is_widget=True, ssr=ssr)
        stale_pages = {registered for registered in self._widgets if registered.path == page_spec.path}
        self._widgets.difference_update(stale_pages)
        self._widgets.add(page_spec)

        # Preserve protocol metadata key/scheme for MCP compatibility.
        meta = meta or {}
        meta["ui"] = {"resourceUri": uri}
        cached_fingerprint: tuple[tuple[str, bool, int | None, int | None], ...] | None = None
        cached_html: str | None = None
        cache_lock = asyncio.Lock()
        client_path = APath(self.output / page_spec.client)
        server_path = APath(self.output / page_spec.server) if page_spec.server else None
        css_path = APath(self.output / page_spec.css)

        async def _compute_fingerprint() -> tuple[tuple[str, bool, int | None, int | None], ...]:
            client_exists = await client_path.exists()
            if not client_exists:
                msg = f"Client bundled output for {widget} not found. Has the bundler been run?"
                raise FileNotFoundError(msg)
            client_stat = await client_path.stat()

            if server_path is None:
                if ssr:
                    msg = f"SSR bundled output for {widget} not found. Has the bundler been run?"
                    raise FileNotFoundError(msg)
                server_fingerprint = ("server", False, None, None)
            else:
                server_exists = await server_path.exists()
                if not server_exists:
                    if ssr:
                        msg = f"SSR bundled output for {widget} not found. Has the bundler been run?"
                        raise FileNotFoundError(msg)
                    server_fingerprint = ("server", False, None, None)
                else:
                    server_stat = await server_path.stat()
                    server_fingerprint = ("server", True, server_stat.st_mtime_ns, server_stat.st_size)

            if await css_path.exists():
                css_stat = await css_path.stat()
                css_fingerprint = ("css", True, css_stat.st_mtime_ns, css_stat.st_size)
            else:
                css_fingerprint = ("css", False, None, None)

            return (
                ("client", True, client_stat.st_mtime_ns, client_stat.st_size),
                server_fingerprint,
                css_fingerprint,
            )

        async def _render_resource_html() -> str:
            client = None if not await client_path.exists() else await client_path.read_text(encoding="utf-8")

            if not client:
                msg = f"Client bundled output for {widget} not found. Has the bundler been run?"
                raise FileNotFoundError(msg)

            server = None
            if server_path and await server_path.exists():
                server = await server_path.read_text(encoding="utf-8")
            html = await run(server) if server else None

            if (not html) and ssr:
                msg = f"SSR bundled output for {widget} not found. Has the bundler been run?"
                raise FileNotFoundError(msg)

            css = None if not await css_path.exists() else await css_path.read_text(encoding="utf-8")

            return ENV.render_template(
                "template.html",
                js=client,
                css=css,
                html=html,
                metadata=merge_metadata(self.metadata, metadata),
            )

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
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
                nonlocal cached_fingerprint
                nonlocal cached_html

                fingerprint = await _compute_fingerprint()
                if self.cache_html and cached_fingerprint == fingerprint and cached_html is not None:
                    return cached_html

                if not self.cache_html:
                    return await _render_resource_html()

                async with cache_lock:
                    fingerprint = await _compute_fingerprint()
                    if cached_fingerprint == fingerprint and cached_html is not None:
                        return cached_html

                    rendered_html = await _render_resource_html()
                    cached_fingerprint = fingerprint
                    cached_html = rendered_html
                    return rendered_html

            return fn

        return decorator
