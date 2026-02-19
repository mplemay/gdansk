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

from gdansk._core import bundle, run
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


@dataclass(frozen=True, slots=True, kw_only=True)
class View:
    path: Path
    app: bool = False
    ssr: bool = False


@dataclass(frozen=True, slots=True)
class Amber:
    _view_ssr: dict[Path, bool] = field(default_factory=dict, init=False)
    _bundle_manifest: dict[str, dict[str, str | None]] = field(default_factory=dict, init=False)
    _template: ClassVar[str] = "template.html"
    _ui_min_parts: ClassVar[int] = 2

    mcp: FastMCP
    views: Path
    output: Path = field(init=False)
    ssr: bool = field(default=False, kw_only=True)
    metadata: Metadata | None = field(default=None, kw_only=True)
    plugins: Sequence[Plugin] = field(default=(), kw_only=True)

    def __post_init__(self) -> None:
        if not self.views.is_dir():
            msg = f"The views directory {self.views} does not exist"
            raise ValueError(msg)

        object.__setattr__(self, "output", self.views / ".gdansk")

    @property
    def paths(self) -> frozenset[Path]:
        return frozenset(self._view_ssr)

    @staticmethod
    def _manifest_key(path: Path) -> str:
        return PurePosixPath(path.as_posix()).as_posix()

    @staticmethod
    def _build_fallback_manifest(views: list[View]) -> dict[str, dict[str, str | None]]:
        manifest: dict[str, dict[str, str | None]] = {}
        for view in views:
            key = Amber._manifest_key(view.path)
            path_posix = PurePosixPath(view.path.as_posix())
            if view.app:
                if len(path_posix.parts) < Amber._ui_min_parts + 1 or path_posix.parts[0] != "apps":
                    msg = f"App view path must be inside apps/**/app.tsx: {view.path}"
                    raise ValueError(msg)
                tool_path = PurePosixPath(*path_posix.parts[1:-1])
                client_stem = tool_path / "client"
                server_stem = tool_path / "server"
            else:
                client_stem = path_posix.with_suffix("")
                server_stem = client_stem
            manifest[key] = {
                "client_js": f"{client_stem}.js",
                "client_css": f"{client_stem}.css",
                "server_js": f"{server_stem}.js" if view.ssr else None,
            }
        return manifest

    def _build_registered_views(self) -> list[View]:
        return [
            View(path=Path("apps", *path.parts), app=True, ssr=ssr)
            for path, ssr in sorted(self._view_ssr.items(), key=lambda item: item[0].as_posix())
        ]

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
                    views=self.views,
                    output=self.output,
                    stop_event=stop_event,
                ),
            )
            for plugin in self.plugins
        ]

        return stop_event, watcher_tasks

    async def _run_build_pipeline(self, *, views: list[View], dev: bool) -> None:
        object.__setattr__(self, "_bundle_manifest", Amber._build_fallback_manifest(views))
        manifest = await bundle(
            views=views,
            dev=dev,
            minify=not dev,
            output=self.output,
            cwd=self.views,
        )
        object.__setattr__(self, "_bundle_manifest", manifest)
        if dev:
            return
        for plugin in self.plugins:
            await plugin.build(views=self.views, output=self.output)

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
    def _normalize_ui_path_and_uri(ui: Path) -> tuple[Path, Path, str]:
        if ui.suffix not in {".tsx", ".jsx"}:
            msg = f"The ui (i.e. {ui}) must be a .tsx or .jsx file"
            raise ValueError(msg)

        if ui.is_absolute():
            msg = f"The ui (i.e. {ui}) must be a relative path"
            raise ValueError(msg)

        ui_posix = PurePosixPath(ui.as_posix())
        if any(part in {"", ".", ".."} for part in ui_posix.parts):
            msg = f"The ui (i.e. {ui}) must not contain traversal segments"
            raise ValueError(msg)

        if (
            len(ui_posix.parts) < Amber._ui_min_parts
            or ui_posix.parts[0] == "apps"
            or ui_posix.name not in {"app.tsx", "app.jsx"}
        ):
            msg = f"The ui (i.e. {ui}) must match **/app.tsx or **/app.jsx and must not start with apps/"
            raise ValueError(msg)

        normalized_ui = Path(*ui_posix.parts)
        bundle_ui = Path("apps", *ui_posix.parts)
        uri = f"ui://{PurePosixPath(*ui_posix.parts[:-1])}"
        return normalized_ui, bundle_ui, uri

    def __call__(self, *, dev: bool = False) -> Starlette:
        app = self.mcp.streamable_http_app()
        if not self._view_ssr:
            return app

        views = self._build_registered_views()
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
            bundle_task = asyncio.create_task(self._run_build_pipeline(views=views, dev=True))
            bundle_task.add_done_callback(self._log_background_task_error)
            for watcher_task in watcher_tasks:
                watcher_task.add_done_callback(self._log_background_task_error)

        @asynccontextmanager
        async def _lifespan(starlette_app: Starlette) -> AsyncIterator[None]:
            if dev:
                runner.run(_start_dev())
            else:
                runner.run(self._run_build_pipeline(views=views, dev=False))

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
        ui: Path,
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
        normalized_ui, bundle_ui, uri = self._normalize_ui_path_and_uri(ui)

        if not (self.views / bundle_ui).is_file():
            msg = f"The ui (i.e. {ui}) was not found"
            raise FileNotFoundError(msg)

        ssr = self.ssr if ssr is None else ssr
        self._view_ssr[normalized_ui] = ssr
        bundle_ui_posix = PurePosixPath(bundle_ui.as_posix())
        tool_path = PurePosixPath(*bundle_ui_posix.parts[1:-1])
        client_stem = tool_path / "client"
        client_js_path = self.output / Path(f"{client_stem}.js")
        client_css_path = self.output / Path(f"{client_stem}.css")
        server_js_path = self.output / Path(f"{tool_path / 'server'}.js")

        # add the ui to the metadata
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
                    if not await (path := APath(client_js_path)).exists()
                    else await path.read_text(encoding="utf-8")
                )

                if not client:
                    msg = f"Bundled output for {ui} not found. Has the bundler been run?"
                    raise FileNotFoundError(msg)

                server = (
                    None
                    if not await (path := APath(server_js_path)).exists()
                    else await path.read_text(encoding="utf-8")
                )
                html = await run(server) if server else None

                if (not html) and ssr:
                    msg = f"Bundled output for {ui} not found. Has the bundler been run?"
                    raise FileNotFoundError(msg)

                css = (
                    None
                    if not await (path := APath(client_css_path)).exists()
                    else await path.read_text(encoding="utf-8")
                )

                return ENV.render_template(
                    Amber._template,
                    js=client,
                    css=css,
                    ssr_html=html,
                    metadata=merge_metadata(self.metadata, metadata),
                )

            return fn

        return decorator
