"""Core integration between FastMCP tools and gdansk widget resources."""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, ClassVar

from anyio import Path as APath
from asyncer import runnify
from gdansk_bundler import Plugin

from gdansk._core import Page, bundle, run
from gdansk.metadata import Metadata, merge_metadata
from gdansk.render import ENV

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from mcp.server import MCPServer as FastMCP
    from mcp.types import Icon, ToolAnnotations
    from starlette.applications import Starlette

    from gdansk.protocol import PathType

logger = logging.getLogger(__name__)


def _validate_plugins(plugins: Sequence[Plugin] | None) -> None:
    if plugins is None:
        return

    for plugin in plugins:
        if isinstance(plugin, Plugin):
            continue

        msg = "Ship plugins must be gdansk_bundler.Plugin instances"
        raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class _ShipBuildState:
    pages: tuple[Page, ...]
    views: Path
    output: Path
    plugins: Sequence[Plugin] | None
    dev: bool
    minify: bool


@dataclass(slots=True)
class _ShipRuntime:
    dev: bool | None = None
    dev_thread: threading.Thread | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


async def _build_ship(state: _ShipBuildState) -> None:
    await bundle(
        pages=list(state.pages),
        dev=state.dev,
        minify=state.minify,
        output=state.output,
        cwd=state.views,
        plugins=state.plugins,
    )


_run_build_sync = runnify(_build_ship)


def _run_build_in_background(state: _ShipBuildState) -> None:
    try:
        _run_build_sync(state)
    except Exception:
        logger.exception("Ship background build failed")


@dataclass(slots=True)
class _WidgetResource:
    ship: Ship
    widget: Path
    page: Page
    metadata: Metadata | None
    ssr: bool
    _cached_html: str | None = None
    _cache_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def _client_path(self) -> APath:
        return APath(self.ship.output / self.page.client)

    def _server_path(self) -> APath | None:
        if self.page.server is None:
            return None
        return APath(self.ship.output / self.page.server)

    def _css_path(self) -> APath:
        return APath(self.ship.output / self.page.css)

    def _should_cache_html(self) -> bool:
        return self.ship.cache_html and self.ship._runtime.dev is not True  # noqa: SLF001

    async def _render_html(self) -> str:
        client_path = self._client_path()
        client = None if not await client_path.exists() else await client_path.read_text(encoding="utf-8")
        if not client:
            msg = f"Client bundled output for {self.widget} not found. Has the bundler been run?"
            raise FileNotFoundError(msg)

        server_path = self._server_path()
        server = (
            None
            if server_path is None or not await server_path.exists()
            else await server_path.read_text(encoding="utf-8")
        )
        html = await run(server) if server else None
        if (not html) and self.ssr:
            msg = f"SSR bundled output for {self.widget} not found. Has the bundler been run?"
            raise FileNotFoundError(msg)

        css_path = self._css_path()
        css = None if not await css_path.exists() else await css_path.read_text(encoding="utf-8")

        return ENV.render_template(
            "template.html",
            js=client,
            css=css,
            html=html,
            metadata=merge_metadata(self.ship.metadata, self.metadata),
        )

    async def __call__(self) -> str:
        if not self._should_cache_html():
            return await self._render_html()

        if self._cached_html is not None:
            return self._cached_html

        async with self._cache_lock:
            if self._cached_html is not None:
                return self._cached_html

            rendered_html = await self._render_html()
            self._cached_html = rendered_html
            return rendered_html


@dataclass(frozen=True, slots=True)
class Ship:
    """Register widget-backed MCP tools and serve their bundled assets."""

    _template: ClassVar[str] = "template.html"
    _page_min_parts: ClassVar[int] = 2

    mcp: FastMCP
    views: PathType
    output: Path = field(init=False)
    ssr: bool = field(default=False, kw_only=True)
    cache_html: bool = field(default=True, kw_only=True)
    metadata: Metadata | None = field(default=None, kw_only=True)
    plugins: Sequence[Plugin] | None = field(default=None, kw_only=True)
    _pages: dict[Path, Page] = field(default_factory=dict, init=False, repr=False)
    _runtime: _ShipRuntime = field(default_factory=_ShipRuntime, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Normalize required paths and validate plugin inputs."""
        views_path = Path(self.views)
        object.__setattr__(self, "views", views_path)
        if not views_path.is_dir():
            msg = f"The views directory {views_path} does not exist"
            raise ValueError(msg)

        _validate_plugins(self.plugins)
        object.__setattr__(self, "output", views_path / ".gdansk")

    @property
    def _widgets(self) -> set[Page]:
        return set(self._pages.values())

    def _views_path(self) -> Path:
        if not isinstance(self.views, Path):
            msg = "internal error: Ship.views was not normalized to pathlib.Path"
            raise TypeError(msg)
        return self.views

    def _registered_pages(self) -> list[Page]:
        return sorted(self._pages.values(), key=lambda page: page.path.as_posix())

    def _register_page(self, page: Page) -> None:
        self._pages[page.path] = page

    @staticmethod
    def _normalize_widget_input(widget: PathType) -> Path:
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
    def _bundle_page_and_uri(widget: Path) -> tuple[Path, str]:
        widget_posix = PurePosixPath(widget.as_posix())
        if (
            len(widget_posix.parts) < Ship._page_min_parts
            or widget_posix.parts[0] == "widgets"
            or widget_posix.name not in {"widget.tsx", "widget.jsx"}
        ):
            msg = (
                f"The widget path (i.e. {widget}) must match **/widget.tsx or **/widget.jsx "
                "and must not start with widgets/"
            )
            raise ValueError(msg)

        bundle_page = Path("widgets", *widget_posix.parts)
        uri = f"ui://{PurePosixPath(*widget_posix.parts[:-1])}"
        return bundle_page, uri

    def _resolve_widget(self, widget: PathType, *, ssr: bool | None) -> tuple[Path, str, Page, bool]:
        widget_path = self._normalize_widget_input(widget)
        widget_candidates = self._resolve_widget_path_candidates(widget_path)

        bundle_page: Path | None = None
        uri: str | None = None
        views_root = self._views_path()
        for widget_candidate in widget_candidates:
            candidate_bundle_page, candidate_uri = self._bundle_page_and_uri(widget_candidate)
            if (views_root / candidate_bundle_page).is_file():
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

        effective_ssr = self.ssr if ssr is None else ssr
        return widget_path, uri, Page(path=bundle_page, is_widget=True, ssr=effective_ssr), effective_ssr

    def __call__(self, *, dev: bool = False) -> Starlette:
        """Build and return the Starlette app that serves registered resources."""
        app = self.mcp.streamable_http_app()
        if not self._pages:
            return app

        build_state = _ShipBuildState(
            pages=tuple(self._registered_pages()),
            views=self._views_path(),
            output=self.output,
            plugins=self.plugins,
            dev=dev,
            minify=not dev,
        )

        with self._runtime.lock:
            active_dev = self._runtime.dev
            if active_dev is not None and active_dev != dev:
                msg = "Ship instances cannot switch between dev and prod modes once started"
                raise RuntimeError(msg)

            if dev:
                self._runtime.dev = True
                dev_thread = self._runtime.dev_thread
                if dev_thread is None or not dev_thread.is_alive():
                    dev_thread = threading.Thread(
                        target=_run_build_in_background,
                        args=(build_state,),
                        name=f"gdansk-ship-{self._views_path().name}",
                        daemon=True,
                    )
                    self._runtime.dev_thread = dev_thread
                    dev_thread.start()
                return app

            _run_build_sync(build_state)
            self._runtime.dev = False
        return app

    def tool(  # noqa: PLR0913
        self,
        widget: PathType,
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
        widget_path, uri, page, effective_ssr = self._resolve_widget(widget, ssr=ssr)
        self._register_page(page)

        tool_meta = {**(meta or {}), "ui": {"resourceUri": uri}}
        resource = _WidgetResource(
            ship=self,
            widget=widget_path,
            page=page,
            metadata=metadata,
            ssr=effective_ssr,
        )

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.mcp.tool(
                name=name,
                title=title,
                description=description,
                annotations=annotations,
                icons=icons,
                meta=tool_meta,
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
                return await resource()

            return fn

        return decorator
