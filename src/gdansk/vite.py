from __future__ import annotations

from asyncio import sleep
from asyncio.subprocess import DEVNULL, PIPE, Process, create_subprocess_exec
from contextlib import suppress
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path  # noqa: TC003
from typing import Final

from deno import find_deno_bin
from httpx import AsyncClient, RequestError

from gdansk.utils import join_url


class Vite:
    def __init__(self, *, host: str = "127.0.0.1", port: int = 13_714) -> None:
        if not (host := host.strip()):
            msg = "The runtime host must not be empty"
            raise ValueError(msg)

        if port <= 0 or port > 65_535:  # noqa: PLR2004
            msg = "The runtime port must be an integer between 1 and 65,535"
            raise ValueError(msg)

        self._deno: Final[str] = find_deno_bin()
        self._host: Final[str] = host
        self._port: Final[int] = port
        self._frontend: Process | None = None
        self._origin: str | None = None
        self._runtime_cwd: Path | None = None
        self._runtime_client: AsyncClient | None = None
        self._context: ViteContext | None = None
        self._vite_context: ViteContext = ViteContext(_vite=self)

    def bind_runtime(self, *, cwd: Path, client: AsyncClient) -> None:
        self._runtime_cwd = cwd
        self._runtime_client = client

    def __call__(self, *, watch: bool | None) -> ViteContext:
        return self._vite_context(watch=watch)

    @property
    def context(self) -> ViteContext:
        return self._vite_context

    def has_runtime(self) -> bool:
        return self._frontend is not None or self._origin is not None

    def require_origin(self) -> str:
        if self._origin is None:
            msg = "The frontend dev server is not running"
            raise RuntimeError(msg)

        return self._origin

    async def run_build(self, cwd: Path) -> None:
        proc = await create_subprocess_exec(
            self._deno,
            "run",
            "-A",
            "--node-modules-dir=auto",
            "npm:vite",
            "build",
            cwd=cwd,
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

    async def start_dev(self, cwd: Path) -> None:
        self._origin = f"http://{self._host}:{self._port}"
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
            cwd=cwd,
            stdin=DEVNULL,
            stdout=DEVNULL,
            stderr=DEVNULL,
        )

    async def wait_for_client(self, client: AsyncClient) -> None:
        if self._frontend is None or self._origin is None:
            msg = "The frontend dev server process has not been started"
            raise RuntimeError(msg)

        client_url = join_url(self._origin, "/@vite/client")

        for _ in range(1200):
            if self._frontend.returncode is not None:
                msg = (
                    "The frontend dev server exited before the Vite client became available "
                    f"(exit code {self._frontend.returncode})"
                )
                raise RuntimeError(msg)

            try:
                response = await client.get(client_url, timeout=0.2)
            except RequestError:
                pass
            else:
                if response.status_code == HTTPStatus.OK:
                    return

            await sleep(0.05)

        msg = (
            f"The frontend dev server did not start in time ({client_url}). "
            f'Ensure Vite(host="{self._host}", port={self._port}) matches '
            f'gdansk({{ host: "{self._host}", port: {self._port} }}).'
        )
        raise RuntimeError(msg)

    async def stop(self) -> None:
        self._origin = None

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


@dataclass(slots=True, kw_only=True)
class ViteContext:
    _vite: Vite
    _watch: bool | None = None

    def __call__(self, *, watch: bool | None) -> ViteContext:
        self._watch = watch
        return self

    async def __aenter__(self) -> None:
        if self._vite._context is not None:  # noqa: SLF001
            msg = "The Vite frontend runtime is already active"
            raise RuntimeError(msg)
        self._vite._context = self  # noqa: SLF001
        try:
            match self._watch:
                case True:
                    if (cwd := self._vite._runtime_cwd) is None:  # noqa: SLF001
                        msg = "Vite is not bound to a views directory (use Ship / ShipContext)"
                        raise RuntimeError(msg)  # noqa: TRY301
                    try:
                        await self._vite.start_dev(cwd)
                    except Exception:
                        await self._vite.stop()
                        raise
                case False:
                    if (cwd := self._vite._runtime_cwd) is None:  # noqa: SLF001
                        msg = "Vite is not bound to a views directory (use Ship / ShipContext)"
                        raise RuntimeError(msg)  # noqa: TRY301
                    try:
                        await self._vite.run_build(cwd)
                    except Exception:
                        await self._vite.stop()
                        raise
                case None:
                    pass
        except Exception:
            self._vite._context = None  # noqa: SLF001
            raise

    async def __aexit__(self, _exc_type: object, _exc: BaseException | None, _tb: object) -> None:
        try:
            await self._vite.stop()
        finally:
            self._vite._context = None  # noqa: SLF001
