from __future__ import annotations

from asyncio import sleep
from asyncio.subprocess import DEVNULL, PIPE, Process, create_subprocess_exec
from contextlib import suppress
from http import HTTPStatus
from os import PathLike
from pathlib import Path, PurePosixPath
from typing import Final

from deno import find_deno_bin
from httpx import AsyncClient, RequestError
from pydantic import ValidationError

from gdansk.manifest import GdanskManifest, WidgetManifest
from gdansk.utils import join_url

type PathType = str | PathLike[str]


class Vite:
    def __init__(
        self,
        root: PathType | None = None,
        *,
        build_directory: str = "dist",
        host: str = "127.0.0.1",
        port: int = 13_714,
    ) -> None:
        if root is None:
            root = Path.cwd() / "views"

        if not (root := Path(root)).exists():
            msg = f"The frontend root directory (i.e. {root}) does not exist"
            raise FileNotFoundError(msg)

        if not root.is_dir():
            msg = f"The frontend root directory (i.e. {root}) is not a directory"
            raise ValueError(msg)

        if not (host := host.strip()):
            msg = "The runtime host must not be empty"
            raise ValueError(msg)

        if port <= 0 or port > 65_535:  # noqa: PLR2004
            msg = "The runtime port must be an integer between 1 and 65,535"
            raise ValueError(msg)

        self._build_directory: Final[str] = self._normalize_relative_directory(
            build_directory,
            name="build",
        )
        self._build_directory_path: Final[Path] = root.absolute().resolve() / self._build_directory
        self._deno: Final[str] = find_deno_bin()
        self._host: Final[str] = host
        self._port: Final[int] = port
        self._root: Final[Path] = root.absolute().resolve()
        self._widgets_root: Final[Path] = self._root / "widgets"

        self._frontend: Process | None = None
        self._manifest: GdanskManifest | None = None
        self._origin: str | None = None

    @property
    def assets_path(self) -> str:
        return PurePosixPath("/", self._build_directory).as_posix()

    @property
    def build_directory(self) -> str:
        return self._build_directory

    @property
    def build_directory_path(self) -> Path:
        return self._build_directory_path

    @property
    def root(self) -> Path:
        return self._root

    @property
    def widgets_root(self) -> Path:
        return self._widgets_root

    @staticmethod
    def _normalize_relative_directory(directory: str, *, name: str) -> str:
        if not (cleaned := directory.strip().strip("/")):
            msg = f"The {name} directory must not be empty"
            raise ValueError(msg)

        posix = PurePosixPath(cleaned)
        if posix.is_absolute() or any(part in {"", ".", ".."} for part in posix.parts):
            msg = f"The {name} directory (i.e. {directory}) must be a relative path without traversal segments"
            raise ValueError(msg)

        return posix.as_posix()

    def clear_manifest(self) -> None:
        self._manifest = None

    def development_asset_path(self, *, widget_key: str) -> str:
        return PurePosixPath("/@gdansk/client", f"{widget_key}.tsx").as_posix()

    def has_runtime(self) -> bool:
        return self._frontend is not None or self._origin is not None

    def load_manifest(self) -> GdanskManifest:
        path = self.manifest_path
        if not path.is_file():
            msg = f"The frontend build did not produce a manifest at {path}"
            raise RuntimeError(msg)

        try:
            manifest = GdanskManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as e:
            msg = f"The frontend build produced an invalid manifest at {path}"
            raise RuntimeError(msg) from e

        if manifest.out_dir.strip("/") != self._build_directory:
            msg = (
                "The frontend build directory does not match the configured build directory. "
                f'Ensure Vite(build_directory="{self._build_directory}") matches '
                f'gdansk({{ buildDirectory: "{self._build_directory}" }}).'
            )
            raise RuntimeError(msg)

        self._manifest = manifest
        return manifest

    @property
    def manifest_path(self) -> Path:
        return self._build_directory_path / "gdansk-manifest.json"

    def require_manifest(self) -> GdanskManifest:
        if self._manifest is None:
            msg = "The production asset manifest is not loaded"
            raise RuntimeError(msg)

        return self._manifest

    def require_manifest_widget(self, widget_key: str) -> WidgetManifest:
        manifest = self.require_manifest()
        if widget_key not in manifest.widgets:
            msg = f'The production asset manifest does not contain the widget "{widget_key}"'
            raise RuntimeError(msg)

        return manifest.widgets[widget_key]

    def require_origin(self) -> str:
        if self._origin is None:
            msg = "The frontend dev server is not running"
            raise RuntimeError(msg)

        return self._origin

    async def build(self) -> None:
        self.clear_manifest()

        proc = await create_subprocess_exec(
            self._deno,
            "run",
            "-A",
            "--node-modules-dir=auto",
            "npm:vite",
            "build",
            cwd=self._root,
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

    async def start_dev(self) -> None:
        self.clear_manifest()
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
            cwd=self._root,
            stdin=DEVNULL,
            stdout=DEVNULL,
            stderr=DEVNULL,
        )

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

    async def wait_until_ready(self, client: AsyncClient) -> None:
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
