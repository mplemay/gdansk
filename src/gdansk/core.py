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

from gdansk._core import Page, bundle, run
from gdansk.metadata import Metadata, merge_metadata
from gdansk.render import ENV

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine, Sequence

    from mcp.server.fastmcp import FastMCP
    from mcp.types import AnyFunction, Icon, ToolAnnotations
    from starlette.applications import Starlette

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
    pages: Path
    output: Path = field(init=False)
    ssr: bool = field(default=False, kw_only=True)
    metadata: Metadata | None = field(default=None, kw_only=True)
    plugins: Sequence[Plugin] = field(default=(), kw_only=True)

    def __post_init__(self) -> None:
        """Validate required paths and initialize derived output paths."""
        if not self.pages.is_dir():
            msg = f"The pages directory {self.pages} does not exist"
            raise ValueError(msg)

        object.__setattr__(self, "output", self.pages / ".gdansk")

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
                    pages=self.pages,
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
            cwd=self.pages,
        )
        if dev:
            return
        for plugin in self.plugins:
            await plugin.build(pages=self.pages, output=self.output)

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
    def _normalize_page_path_and_uri(page: Path) -> tuple[Path, Path, str]:
        if page.suffix not in {".tsx", ".jsx"}:
            msg = f"The page (i.e. {page}) must be a .tsx or .jsx file"
            raise ValueError(msg)

        if page.is_absolute():
            msg = f"The page (i.e. {page}) must be a relative path"
            raise ValueError(msg)

        page_posix = PurePosixPath(page.as_posix())
        if any(part in {"", ".", ".."} for part in page_posix.parts):
            msg = f"The page (i.e. {page}) must not contain traversal segments"
            raise ValueError(msg)

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

    def tool(  # noqa: PLR0913
        self,
        page: Path,
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
        _, bundle_page, uri = self._normalize_page_path_and_uri(page)

        if not (self.pages / bundle_page).is_file():
            msg = f"The page (i.e. {page}) was not found"
            raise FileNotFoundError(msg)

        ssr = self.ssr if ssr is None else ssr
        page_spec = Page(path=bundle_page, app=True, ssr=ssr)
        stale_pages = {registered for registered in self._apps if registered.path == page_spec.path}
        self._apps.difference_update(stale_pages)
        self._apps.add(page_spec)

        # Preserve protocol metadata key/scheme for MCP compatibility.
        meta = meta or {}
        meta["ui"] = {"resourceUri": uri}

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
                client = (
                    None
                    if not await (path := APath(self.output / page_spec.client)).exists()
                    else await path.read_text(encoding="utf-8")
                )

                if not client:
                    msg = f"Client bundled output for {page} not found. Has the bundler been run?"
                    raise FileNotFoundError(msg)

                server = None
                if page_spec.server and await (path := APath(self.output / page_spec.server)).exists():
                    server = await path.read_text(encoding="utf-8")
                html = await run(server) if server else None

                if (not html) and ssr:
                    msg = f"SSR bundled output for {page} not found. Has the bundler been run?"
                    raise FileNotFoundError(msg)

                css = (
                    None
                    if not await (path := APath(self.output / page_spec.css)).exists()
                    else await path.read_text(encoding="utf-8")
                )

                return ENV.render_template(
                    "template.html",
                    js=client,
                    css=css,
                    html=html,
                    metadata=merge_metadata(self.metadata, metadata),
                )

            return fn

        return decorator
