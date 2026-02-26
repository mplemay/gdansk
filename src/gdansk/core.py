"""Core integration between FastMCP tools and gdansk page resources."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, ClassVar

from anyio import Path as APath, create_task_group
from anyio.from_thread import start_blocking_portal
from asyncer import asyncify

from gdansk._core import Page, bundle, run
from gdansk.metadata import Metadata, merge_metadata
from gdansk.render import ENV

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
    from os import PathLike

    from mcp.server.fastmcp import FastMCP
    from mcp.types import AnyFunction, Icon, ToolAnnotations
    from starlette.applications import Starlette

    from gdansk.protocol import Plugin


logger = logging.getLogger(__name__)


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
            await asyncio.wait_for(
                plugin(pages=self.views, output=self.output),
                timeout=plugin.timeout,
            )

    @staticmethod
    async def _run_background(task: Callable[[], Awaitable[None]]) -> None:
        try:
            await task()
        except asyncio.CancelledError as exc:
            raise exc from exc
        except Exception as exc:
            logger.exception("Amber background task failed", exc_info=exc)

    @staticmethod
    async def _poll_plugin(
        task: Callable[[], Awaitable[None]],
        stop_event: asyncio.Event,
        timeout: float,
    ) -> None:
        while not stop_event.is_set():
            await Amber._run_background(task)

            if timeout <= 0:
                await asyncio.sleep(0)
                continue

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=timeout)
            except TimeoutError:
                continue

    async def _run_dev_tasks(self, *, stop_event: asyncio.Event) -> None:
        async with create_task_group() as task_group:
            task_group.start_soon(
                Amber._run_background,
                partial(self._run_build_pipeline, dev=True),
            )
            for plugin in self.plugins:
                task_group.start_soon(
                    Amber._poll_plugin,
                    partial(plugin, pages=self.views, output=self.output),
                    stop_event,
                    plugin.timeout,
                )
            await stop_event.wait()
            task_group.cancel_scope.cancel()

    @asynccontextmanager
    async def pipeline(self, *, dev: bool) -> AsyncIterator[None]:
        with start_blocking_portal(backend="asyncio") as portal:
            portal_call = asyncify(portal.call)
            stop_event: asyncio.Event | None = None
            dev_future = None

            if dev:
                stop_event = await portal_call(asyncio.Event)
                dev_future = portal.start_task_soon(partial(self._run_dev_tasks, stop_event=stop_event))
            else:
                await portal_call(partial(self._run_build_pipeline, dev=False))

            try:
                yield
            finally:
                if dev and stop_event is not None and dev_future is not None:
                    await portal_call(stop_event.set)
                    await asyncify(dev_future.result)()

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

        original = app.router.lifespan_context

        @asynccontextmanager
        async def new(starlette_app: Starlette) -> AsyncIterator[None]:
            async with self.pipeline(dev=dev), original(starlette_app):
                yield

        app.router.lifespan_context = new

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
