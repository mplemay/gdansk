from __future__ import annotations

from asyncio import sleep
from asyncio.subprocess import DEVNULL, PIPE, Process, create_subprocess_exec
from contextlib import asynccontextmanager, suppress
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

from deno import find_deno_bin
from httpx import AsyncClient, RequestError
from pydantic import ValidationError

from gdansk.manifest import GdanskManifest, WidgetManifest
from gdansk.metadata import Metadata  # noqa: TC001 (MCP validate_call evaluates render_widget_page annotations)
from gdansk.render import render_template
from gdansk.utils import join_url, join_url_path

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


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
        self._manifest: GdanskManifest | None = None
        self._vite_origin: str | None = None

    @asynccontextmanager
    async def open(self, *, watch: bool | None) -> AsyncIterator[None]:
        if self._active:
            msg = "The frontend runtime context is already active"
            raise RuntimeError(msg)

        self._active = True
        try:
            await self._start(watch=watch)
            try:
                yield None
            finally:
                await self._stop()
        finally:
            self._active = False

    async def render_widget_page(self, *, metadata: Metadata | None, widget_key: str) -> str:
        body = ""
        head: list[str] = []
        runtime_origin: str | None = None

        if self._dev:
            runtime_origin = self._require_vite_origin()
            scripts = [
                join_url(runtime_origin, "/@vite/client"),
                join_url(runtime_origin, self._development_asset_path(widget_key=widget_key)),
            ]
        else:
            widget = self._require_manifest_widget(widget_key)
            scripts = [self._manifest_asset_url(widget.client)]
            head = [f'<link rel="stylesheet" href="{self._manifest_asset_url(href)}">' for href in widget.css]

        return render_template(
            "base.html",
            body=body,
            dev=self._dev,
            head=head,
            metadata=metadata,
            runtime_origin=runtime_origin,
            scripts=scripts,
        )

    def _require_manifest(self) -> GdanskManifest:
        if self._manifest is None:
            msg = "The production asset manifest is not loaded"
            raise RuntimeError(msg)

        return self._manifest

    def _require_manifest_widget(self, widget_key: str) -> WidgetManifest:
        manifest = self._require_manifest()
        if widget_key not in manifest.widgets:
            msg = f'The production asset manifest does not contain the widget "{widget_key}"'
            raise RuntimeError(msg)

        return manifest.widgets[widget_key]

    def _require_vite_origin(self) -> str:
        if self._vite_origin is None:
            msg = "The frontend dev server is not running"
            raise RuntimeError(msg)

        return self._vite_origin

    def _asset_base_url(self) -> str | None:
        if self._base_url is None:
            return None

        return join_url_path(self._base_url, self._assets_dir)

    def _asset_url(self, path: str) -> str:
        normalized = path.lstrip("/")
        if (asset_base_url := self._asset_base_url()) is not None:
            return join_url_path(asset_base_url, normalized)

        return PurePosixPath("/", self._assets_dir, normalized).as_posix()

    def _manifest_asset_url(self, path: str) -> str:
        normalized = path.lstrip("/")
        out_dir = self._require_manifest().out_dir.strip("/")
        prefix = f"{out_dir}/"
        relative_path = normalized.removeprefix(prefix)
        return self._asset_url(relative_path)

    @staticmethod
    def _development_asset_path(*, widget_key: str) -> str:
        return PurePosixPath("/@gdansk/client", f"{widget_key}.tsx").as_posix()

    def _manifest_path(self) -> Path:
        return self._views / self._assets_dir / "gdansk-manifest.json"

    def _load_manifest(self) -> GdanskManifest:
        path = self._manifest_path()
        if not path.is_file():
            msg = f"The frontend build did not produce a manifest at {path}"
            raise RuntimeError(msg)

        try:
            manifest = GdanskManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as e:
            msg = f"The frontend build produced an invalid manifest at {path}"
            raise RuntimeError(msg) from e

        if manifest.out_dir.strip("/") != self._assets_dir:
            msg = (
                "The frontend build directory does not match the configured assets directory. "
                f'Ensure Ship(assets="{self._assets_dir}") matches '
                f'gdansk({{ buildDirectory: "{self._assets_dir}" }}).'
            )
            raise RuntimeError(msg)

        return manifest

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

    async def _start(self, *, watch: bool | None) -> None:
        if self._frontend is not None or self._manifest is not None or self._vite_origin is not None:
            msg = "The frontend runtime context is already active"
            raise RuntimeError(msg)

        self._dev = watch is True

        try:
            match watch:
                case True:
                    self._vite_origin = f"http://{self._host}:{self._port}"
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
                    self._frontend = await create_subprocess_exec(
                        *command,
                        cwd=self._views,
                        stdin=DEVNULL,
                        stdout=DEVNULL,
                        stderr=DEVNULL,
                    )
                    await self._wait_for_vite()
                case False:
                    await self._run_build()
                    self._manifest = self._load_manifest()
                case None:
                    self._manifest = self._load_manifest()
        except Exception:
            await self._stop()
            raise

    async def _stop(self) -> None:
        self._dev = False
        self._manifest = None
        self._vite_origin = None

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

    async def _wait_for_vite(self) -> None:
        if self._frontend is None or self._vite_origin is None:
            msg = "The frontend dev server process has not been started"
            raise RuntimeError(msg)

        client_url = join_url(self._vite_origin, "/@vite/client")

        for _ in range(1200):
            if self._frontend.returncode is not None:
                msg = (
                    "The frontend dev server exited before the Vite client became available "
                    f"(exit code {self._frontend.returncode})"
                )
                raise RuntimeError(msg)

            try:
                response = await self._client.get(client_url, timeout=0.2)
            except RequestError:
                pass
            else:
                if response.status_code == HTTPStatus.OK:
                    return

            await sleep(0.05)

        msg = (
            f"The frontend dev server did not start in time ({client_url}). "
            f'Ensure Ship(host="{self._host}", port={self._port}) matches '
            f'gdansk({{ host: "{self._host}", port: {self._port} }}).'
        )
        raise RuntimeError(msg)
