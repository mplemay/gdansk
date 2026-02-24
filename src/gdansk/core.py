"""Core integration between FastMCP tools and gdansk page resources."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from anyio import Path as APath
from starlette.applications import Starlette
from starlette.responses import HTMLResponse
from starlette.routing import Route

from gdansk._core import Page, bundle, run
from gdansk.metadata import Metadata, merge_metadata
from gdansk.render import ENV

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine, Sequence
    from os import PathLike

    from mcp.server.fastmcp import FastMCP
    from mcp.types import AnyFunction, Icon, ToolAnnotations

    from gdansk.protocol import Plugin


logger = logging.getLogger(__name__)
_T = TypeVar("_T")


class _AsyncThreadRunner:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._started.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._started.wait()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._started.set()
        try:
            loop.run_forever()
        finally:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                with suppress(asyncio.CancelledError):
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    def run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        self.start()
        loop = self._loop
        if loop is None:
            msg = "Runner event loop was not started"
            raise RuntimeError(msg)
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()

    def stop(self) -> None:
        if self._loop is None or self._thread is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()
        self._loop = None
        self._thread = None


@dataclass(frozen=True, slots=True)
class Amber:
    """Registers page-backed MCP tools and serves their bundled assets."""

    _apps: set[Page] = field(default_factory=set, init=False)
    _template: ClassVar[str] = "template.html"
    _page_min_parts: ClassVar[int] = 2

    mcp: FastMCP
    views: Path
    output: Path = field(init=False)
    ssr: bool = field(default=False, kw_only=True)
    cache_html: bool = field(default=True, kw_only=True)
    metadata: Metadata | None = field(default=None, kw_only=True)
    plugins: Sequence[Plugin] = field(default=(), kw_only=True)

    def __post_init__(self) -> None:
        """Validate required paths and initialize derived output paths."""
        if not self.views.is_dir():
            msg = f"The views directory {self.views} does not exist"
            raise ValueError(msg)

        object.__setattr__(self, "output", self.views / ".gdansk")

    def _schedule_watcher_tasks(
        self,
        *,
        dev: bool,
    ) -> tuple[asyncio.Event | None, list[asyncio.Task[None]]]:
        if not dev or not self.plugins:
            return None, []

        stop_event = asyncio.Event()
        watcher_tasks: list[asyncio.Task[None]] = [
            asyncio.create_task(
                plugin.watch(
                    pages=self.views,
                    output=self.output,
                    stop_event=stop_event,
                ),
            )
            for plugin in self.plugins
        ]

        return stop_event, watcher_tasks

    async def _run_build_pipeline(self, *, dev: bool) -> None:
        await bundle(
            pages=sorted(self._apps, key=lambda page: page.path.as_posix()),
            dev=dev,
            minify=not dev,
            output=self.output,
            cwd=self.views,
        )
        if dev:
            return
        for plugin in self.plugins:
            await plugin.build(pages=self.views, output=self.output)

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
        stop_event: asyncio.Event | None,
        bundle_task: asyncio.Task[None] | None,
        watcher_tasks: list[asyncio.Task[None]],
    ) -> None:
        if stop_event is not None:
            stop_event.set()
        tasks = [candidate for candidate in [bundle_task, *watcher_tasks] if candidate is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _normalize_page_input(page: str | PathLike[str]) -> Path:
        page_path = Path(page)
        if page_path.is_absolute():
            msg = f"The page (i.e. {page}) must be a relative path"
            raise ValueError(msg)

        page_posix = PurePosixPath(page_path.as_posix())
        if any(part in {"", ".", ".."} for part in page_posix.parts):
            msg = f"The page (i.e. {page}) must not contain traversal segments"
            raise ValueError(msg)

        if page_posix.parts and page_posix.parts[0] == "apps":
            msg = f"The page (i.e. {page}) must not start with apps/"
            raise ValueError(msg)

        return Path(*page_posix.parts)

    @staticmethod
    def _resolve_page_candidates(page: Path) -> tuple[Path, ...]:
        if page.suffix:
            if page.suffix not in {".tsx", ".jsx"}:
                msg = f"The page (i.e. {page}) must be a .tsx or .jsx file"
                raise ValueError(msg)
            if page.name not in {"page.tsx", "page.jsx"}:
                msg = f"The page (i.e. {page}) must match **/page.tsx or **/page.jsx and must not start with apps/"
                raise ValueError(msg)
            return (page,)

        return (page / "page.tsx", page / "page.jsx")

    @staticmethod
    def _normalize_page_path_and_uri(page: Path) -> tuple[Path, Path, str]:
        page_posix = PurePosixPath(page.as_posix())

        if (
            len(page_posix.parts) < Amber._page_min_parts
            or page_posix.parts[0] == "apps"
            or page_posix.name not in {"page.tsx", "page.jsx"}
        ):
            msg = f"The page (i.e. {page}) must match **/page.tsx or **/page.jsx and must not start with apps/"
            raise ValueError(msg)

        normalized_page = Path(*page_posix.parts)
        bundle_page = Path("apps", *page_posix.parts)
        uri = f"ui://{PurePosixPath(*page_posix.parts[:-1])}"
        return normalized_page, bundle_page, uri

    def __call__(self, *, dev: bool = False) -> Starlette:
        """Build and return the Starlette app that serves registered resources."""
        app = self.mcp.streamable_http_app()
        if not self._apps:
            return app

        runner = _AsyncThreadRunner()
        stop_event: asyncio.Event | None = None
        watcher_tasks: list[asyncio.Task[None]] = []
        bundle_task: asyncio.Task[None] | None = None
        original_lifespan = app.router.lifespan_context

        async def _start_dev() -> None:
            nonlocal stop_event
            nonlocal watcher_tasks
            nonlocal bundle_task
            stop_event, watcher_tasks = self._schedule_watcher_tasks(dev=True)
            bundle_task = asyncio.create_task(self._run_build_pipeline(dev=True))
            bundle_task.add_done_callback(self._log_background_task_error)
            for watcher_task in watcher_tasks:
                watcher_task.add_done_callback(self._log_background_task_error)

        @asynccontextmanager
        async def _lifespan(starlette_app: Starlette) -> AsyncIterator[None]:
            if dev:
                runner.run(_start_dev())
            else:
                runner.run(self._run_build_pipeline(dev=False))

            async with original_lifespan(starlette_app):
                try:
                    yield
                finally:
                    if dev:
                        with suppress(concurrent.futures.CancelledError):
                            runner.run(
                                Amber._shutdown_dev_tasks(
                                    stop_event=stop_event,
                                    bundle_task=bundle_task,
                                    watcher_tasks=watcher_tasks,
                                ),
                            )
                    runner.stop()

        app.router.lifespan_context = _lifespan
        return app

    def tool(  # noqa: C901, PLR0913, PLR0915
        self,
        page: str | PathLike[str],
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
    ) -> Callable[[AnyFunction], AnyFunction]:
        """Register a tool and bind its page resource into the MCP server."""
        page_path = self._normalize_page_input(page)
        page_candidates = self._resolve_page_candidates(page_path)

        bundle_page: Path | None = None
        uri: str | None = None

        for page_candidate in page_candidates:
            _, candidate_bundle_page, candidate_uri = self._normalize_page_path_and_uri(page_candidate)
            if (self.views / candidate_bundle_page).is_file():
                bundle_page = candidate_bundle_page
                uri = candidate_uri
                break

        if bundle_page is None or uri is None:
            if len(page_candidates) == 1:
                msg = f"The page (i.e. {page_path}) was not found"
            else:
                msg = (
                    f"The page (i.e. {page_path}) was not found. "
                    f"Expected one of: {page_candidates[0]}, {page_candidates[1]}"
                )
            raise FileNotFoundError(msg)

        ssr = self.ssr if ssr is None else ssr
        page_spec = Page(path=bundle_page, app=True, ssr=ssr)
        stale_pages = {registered for registered in self._apps if registered.path == page_spec.path}
        self._apps.difference_update(stale_pages)
        self._apps.add(page_spec)

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
                msg = f"Client bundled output for {page} not found. Has the bundler been run?"
                raise FileNotFoundError(msg)
            client_stat = await client_path.stat()

            if server_path is None:
                if ssr:
                    msg = f"SSR bundled output for {page} not found. Has the bundler been run?"
                    raise FileNotFoundError(msg)
                server_fingerprint = ("server", False, None, None)
            else:
                server_exists = await server_path.exists()
                if not server_exists:
                    if ssr:
                        msg = f"SSR bundled output for {page} not found. Has the bundler been run?"
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
                msg = f"Client bundled output for {page} not found. Has the bundler been run?"
                raise FileNotFoundError(msg)

            server = None
            if server_path and await server_path.exists():
                server = await server_path.read_text(encoding="utf-8")
            html = await run(server) if server else None

            if (not html) and ssr:
                msg = f"SSR bundled output for {page} not found. Has the bundler been run?"
                raise FileNotFoundError(msg)

            css = None if not await css_path.exists() else await css_path.read_text(encoding="utf-8")

            return ENV.render_template(
                "template.html",
                js=client,
                css=css,
                html=html,
                metadata=merge_metadata(self.metadata, metadata),
            )

        def decorator(fn: AnyFunction) -> AnyFunction:
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


@dataclass(frozen=True, slots=True)
class Ship:
    """Registers web pages and serves bundled HTML routes."""

    _pages: dict[str, Page] = field(default_factory=dict, init=False)
    _template: ClassVar[str] = "template.html"
    _page_min_parts: ClassVar[int] = 1

    views: Path
    output: Path = field(init=False)

    def __post_init__(self) -> None:
        """Validate required paths and initialize derived output paths."""
        if not self.views.is_dir():
            msg = f"The views directory {self.views} does not exist"
            raise ValueError(msg)

        object.__setattr__(self, "output", self.views / ".gdansk")

    @staticmethod
    def _normalize_page_input(page: Path) -> Path:
        if page.is_absolute():
            msg = f"The page (i.e. {page}) must be a relative path"
            raise ValueError(msg)

        page_posix = PurePosixPath(page.as_posix())
        if any(part in {"", ".", ".."} for part in page_posix.parts):
            msg = f"The page (i.e. {page}) must not contain traversal segments"
            raise ValueError(msg)

        if page_posix.parts and page_posix.parts[0] == "app":
            msg = f"The page (i.e. {page}) must not start with app/"
            raise ValueError(msg)

        return Path(*page_posix.parts)

    @staticmethod
    def _resolve_page_candidates(page: Path) -> tuple[Path, ...]:
        if page.suffix:
            if page.suffix not in {".tsx", ".jsx"}:
                msg = f"The page (i.e. {page}) must be a .tsx or .jsx file"
                raise ValueError(msg)
            if page.name not in {"page.tsx", "page.jsx"}:
                msg = f"The page (i.e. {page}) must match **/page.tsx or **/page.jsx and must not start with app/"
                raise ValueError(msg)
            return (page,)

        return (page / "page.tsx", page / "page.jsx")

    @staticmethod
    def _normalize_page_path_and_route(page: Path) -> tuple[Path, Path, str]:
        page_posix = PurePosixPath(page.as_posix())

        if (
            len(page_posix.parts) < Ship._page_min_parts
            or page_posix.parts[0] == "app"
            or page_posix.name not in {"page.tsx", "page.jsx"}
        ):
            msg = f"The page (i.e. {page}) must match **/page.tsx or **/page.jsx and must not start with app/"
            raise ValueError(msg)

        normalized_page = Path(*page_posix.parts)
        bundle_page = Path("app", *page_posix.parts)
        route_parts = page_posix.parts[:-1]
        route = "/" if not route_parts else "/" + "/".join(route_parts)
        return normalized_page, bundle_page, route

    def include_page(self, *, page: Page) -> None:
        """Register a page and map it to a web route."""
        page_path = self._normalize_page_input(page.path)
        page_candidates = self._resolve_page_candidates(page_path)

        bundle_page: Path | None = None
        route: str | None = None

        for page_candidate in page_candidates:
            _, candidate_bundle_page, candidate_route = self._normalize_page_path_and_route(page_candidate)
            if (self.views / candidate_bundle_page).is_file():
                bundle_page = candidate_bundle_page
                route = candidate_route
                break

        if bundle_page is None or route is None:
            if len(page_candidates) == 1:
                msg = f"The page (i.e. {page_path}) was not found"
            else:
                msg = (
                    f"The page (i.e. {page_path}) was not found. "
                    f"Expected one of: {page_candidates[0]}, {page_candidates[1]}"
                )
            raise FileNotFoundError(msg)

        self._pages[route] = Page(path=bundle_page)

    async def _run_build(self, *, dev: bool) -> None:
        await bundle(
            pages=sorted(self._pages.values(), key=lambda page: page.path.as_posix()),
            dev=False,
            minify=not dev,
            output=self.output,
            cwd=self.views,
        )

    def __call__(self, *, dev: bool = False) -> Starlette:
        """Build and return the Starlette app that serves registered pages."""
        if self._pages:
            runner = _AsyncThreadRunner()
            try:
                runner.run(self._run_build(dev=dev))
            finally:
                runner.stop()

        routes: list[Route] = []
        for route, page in sorted(self._pages.items()):
            client_path = APath(self.output / page.client)
            css_path = APath(self.output / page.css)
            page_path = page.path

            async def _handler(
                _request: object,
                *,
                client_path: APath = client_path,
                css_path: APath = css_path,
                page_path: Path = page_path,
            ) -> HTMLResponse:
                client = None if not await client_path.exists() else await client_path.read_text(encoding="utf-8")
                if not client:
                    msg = f"Client bundled output for {page_path} not found. Has the bundler been run?"
                    raise FileNotFoundError(msg)

                css = None if not await css_path.exists() else await css_path.read_text(encoding="utf-8")
                html = ENV.render_template(
                    Ship._template,
                    js=client,
                    css=css,
                    html=None,
                    metadata=None,
                )
                return HTMLResponse(content=html)

            routes.append(Route(route, endpoint=_handler, methods=["GET"]))

        return Starlette(routes=routes)
