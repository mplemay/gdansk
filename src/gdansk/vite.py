from __future__ import annotations

from asyncio import sleep
from asyncio.subprocess import DEVNULL, PIPE, Process, create_subprocess_exec
from contextlib import suppress
from http import HTTPStatus
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

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
