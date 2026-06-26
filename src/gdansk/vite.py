from __future__ import annotations

from asyncio import sleep
from http import HTTPStatus
from importlib.metadata import version as package_version
from os import PathLike
from pathlib import Path, PurePosixPath
from typing import Final

from belgie import Runtime, Script
from httpx import AsyncClient, RequestError
from pydantic import ValidationError

from gdansk._project import discover_project
from gdansk.manifest import GdanskManifest, WidgetManifest
from gdansk.packages import create_environment
from gdansk.task import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    CommandProcess,
    dev_command_argv,
    start_project_command,
    task_origin,
)
from gdansk.utils import join_url

type PathType = str | PathLike[str]

GDANSK_BUILD_SCRIPT_SOURCE: Final[str] = """
import { createGdanskRuntime } from "@gdansk/vite";

export default async function run(options) {
  const runtime = await createGdanskRuntime(options);
  return await runtime.build();
}
"""

GDANSK_VERSION_SCRIPT_SOURCE: Final[str] = """
import { GDANSK_VERSION } from "@gdansk/vite";

export default function run() {
  return GDANSK_VERSION;
}
"""


class Vite:
    def __init__(
        self,
        root: PathType | None = None,
        *,
        build_directory: str = "dist",
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
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
        self._host: Final[str] = host
        self._port: Final[int] = port
        self._root: Final[Path] = root.absolute().resolve()
        self._widgets_root: Final[Path] = self._root / "widgets"

        self._frontend: CommandProcess | None = None
        self._manifest: GdanskManifest | None = None
        self._origin: str | None = None

    @property
    def build_directory(self) -> str:
        return self._build_directory

    @property
    def build_directory_path(self) -> Path:
        return self._build_directory_path

    def has_manifest(self) -> bool:
        return self._manifest is not None

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
        return self._frontend is not None

    def load_manifest(self) -> GdanskManifest:
        return self.require_manifest()

    def require_manifest(self) -> GdanskManifest:
        if self._manifest is None:
            msg = "The production asset manifest is not loaded"
            raise RuntimeError(msg)

        return self._manifest

    def require_manifest_widget(self, widget_key: str) -> WidgetManifest:
        manifest = self.require_manifest()
        if (widget := manifest.widgets.get(widget_key)) is None:
            msg = f'The production asset manifest does not contain the widget "{widget_key}"'
            raise RuntimeError(msg)

        return widget

    def require_origin(self) -> str:
        if self._origin is None:
            msg = "The frontend dev server is not running"
            raise RuntimeError(msg)

        return self._origin

    async def build(self) -> GdanskManifest:
        self.clear_manifest()
        await self._require_version_match()
        manifest = await self._run_build_script()

        if manifest.out_dir.strip("/") != self._build_directory:
            msg = (
                "The frontend build directory does not match the configured build directory. "
                f'Ensure Vite(build_directory="{self._build_directory}") matches '
                f'gdansk({{ buildDirectory: "{self._build_directory}" }}).'
            )
            raise RuntimeError(msg)

        self._manifest = manifest
        return manifest

    async def start_dev(self) -> None:
        self.clear_manifest()
        if self._frontend is not None:
            if self._frontend.is_running:
                return
            self._frontend = None
            self._origin = None

        await self._require_version_match()
        self._frontend = await start_project_command(
            self._root,
            "vite",
            cwd=self._root,
            argv=dev_command_argv(self._host, self._port),
        )
        self._origin = task_origin(self._host, self._port)

    async def stop(self) -> None:
        frontend = self._frontend
        self._frontend = None
        self._origin = None
        if frontend is not None:
            await frontend.stop()

    async def wait_until_ready(self, client: AsyncClient) -> None:
        if self._origin is None:
            msg = "The frontend dev server has not been started"
            raise RuntimeError(msg)

        client_url = join_url(self._origin, "/@vite/client")

        for _ in range(1200):
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

    async def _require_version_match(self) -> None:
        ts_version = await self._run_version_script()
        if not isinstance(ts_version, str):
            msg = "The frontend runtime reported an invalid belgie package version"
            raise TypeError(msg)

        python_version = package_version("gdansk")
        if python_version != ts_version:
            msg = (
                "The Python and TypeScript belgie package versions do not match. "
                f"Python gdansk={python_version}, @gdansk/vite={ts_version}."
            )
            raise RuntimeError(msg)

    async def _run_build_script(self) -> GdanskManifest:
        manifest = await self._run_package_script(GDANSK_BUILD_SCRIPT_SOURCE, self._bridge_options())
        try:
            return GdanskManifest.model_validate(manifest)
        except ValidationError as exc:
            msg = "The frontend build produced an invalid manifest"
            raise RuntimeError(msg) from exc

    async def _run_package_script(self, source: str, options: dict[str, object] | None = None) -> object:
        project = discover_project(start=self._root)
        environment = create_environment(project, frozen=True)
        async with environment as active_environment:
            await active_environment.install()
            async with Runtime(env=active_environment) as runtime:
                runner = runtime(Script(source))
                return await runner(options) if options is not None else await runner()

    async def _run_version_script(self) -> object:
        return await self._run_package_script(GDANSK_VERSION_SCRIPT_SOURCE)

    def _bridge_options(self) -> dict[str, object]:
        return {
            "buildDirectory": self._build_directory,
            "host": self._host,
            "port": self._port,
            "root": str(self._root),
        }
