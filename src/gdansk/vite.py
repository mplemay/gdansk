from __future__ import annotations

from asyncio import sleep
from json import dumps
from os import PathLike
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Final

from httpx import AsyncClient, RequestError
from pydantic import ValidationError

from gdansk.manifest import DevelopmentWidgetManifest, GdanskDevelopmentManifest, GdanskManifest, WidgetManifest
from gdansk.task import DEFAULT_HOST, DEFAULT_PORT, CommandProcess, run_widget_command, start_widget_command

type PathType = str | PathLike[str]


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

        self._build_directory: Final[str] = self._normalize_relative_directory(build_directory, name="build")
        self._build_directory_path: Final[Path] = root.absolute().resolve() / self._build_directory
        self._host: Final[str] = host
        self._port: Final[int] = port
        self._root: Final[Path] = root.absolute().resolve()
        self._widgets_root: Final[Path] = self._root / "widgets"
        self._development_manifest: GdanskDevelopmentManifest | None = None
        self._frontend: CommandProcess | None = None
        self._manifest: GdanskManifest | None = None
        self._runtime_directory: TemporaryDirectory[str] | None = None

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
        self._development_manifest = None

    def development_widget(self, widget_key: str) -> DevelopmentWidgetManifest:
        if self._development_manifest is None:
            msg = "The development manifest is not loaded"
            raise RuntimeError(msg)
        if (widget := self._development_manifest.widgets.get(widget_key)) is None:
            msg = f'The development manifest does not contain the widget "{widget_key}"'
            raise RuntimeError(msg)
        return widget

    def has_runtime(self) -> bool:
        return self._frontend is not None

    def load_manifest(self) -> GdanskManifest:
        if not (path := self.manifest_path).is_file():
            msg = f"The frontend build did not produce a manifest at {path}"
            raise RuntimeError(msg)
        try:
            manifest = GdanskManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as exc:
            msg = f"The frontend build produced an invalid manifest at {path}"
            raise RuntimeError(msg) from exc
        if manifest.out_dir.strip("/") != self._build_directory:
            msg = f"The frontend build does not match the configured build directory {self._build_directory!r}"
            raise RuntimeError(msg)
        self._manifest = manifest
        return manifest

    @property
    def manifest_path(self) -> Path:
        return self._build_directory_path / "gdansk-manifest.json"

    def require_manifest_widget(self, widget_key: str) -> WidgetManifest:
        manifest = self.require_manifest()
        if (widget := manifest.widgets.get(widget_key)) is None:
            msg = f'The production widget manifest does not contain the widget "{widget_key}"'
            raise RuntimeError(msg)
        return widget

    def require_manifest(self) -> GdanskManifest:
        if self._manifest is None:
            msg = "The production widget manifest is not loaded"
            raise RuntimeError(msg)
        return self._manifest

    async def build(self) -> None:
        source = (
            'import { buildProject } from "@gdansk/widget";\n'
            "export default async () => await buildProject("
            f"{dumps(str(self._root))}, {dumps(self._build_directory)});\n"
        )
        await run_widget_command(
            self._root,
            ["build", "--root", str(self._root), "--out-dir", self._build_directory],
            local_source=source,
        )

    async def start_dev(self) -> CommandProcess:
        if self._frontend is not None:
            if self._frontend.is_running:
                return self._frontend
            self._frontend = None
        self.clear_manifest()
        self._cleanup_runtime_directory()
        self._runtime_directory = TemporaryDirectory(prefix="gdansk-runtime-")
        manifest = Path(self._runtime_directory.name) / "manifest.json"
        source = (
            'import { startDevelopment } from "@gdansk/widget";\n'
            "export default async () => await startDevelopment({"
            f"host: {dumps(self._host)}, manifest: {dumps(str(manifest))}, "
            f"port: {self._port}, root: {dumps(str(self._root))}"
            "});\n"
        )
        self._frontend = await start_widget_command(
            self._root,
            [
                "dev",
                "--root",
                str(self._root),
                "--host",
                self._host,
                "--port",
                str(self._port),
                "--manifest",
                str(manifest),
            ],
            local_source=source,
        )
        return self._frontend

    async def stop(self) -> None:
        frontend = self._frontend
        self._frontend = None
        try:
            if frontend is not None:
                await frontend.stop()
        finally:
            self._cleanup_runtime_directory()
            self._development_manifest = None

    async def wait_until_ready(self, client: AsyncClient) -> None:
        if self._runtime_directory is None:
            msg = "The frontend dev server has not been started"
            raise RuntimeError(msg)
        path = Path(self._runtime_directory.name) / "manifest.json"
        for _ in range(1200):
            if path.is_file():
                try:
                    manifest = GdanskDevelopmentManifest.model_validate_json(path.read_text(encoding="utf-8"))
                    for widget in manifest.widgets.values():
                        response = await client.get(widget.page, timeout=0.2)
                        response.raise_for_status()
                except (OSError, RequestError, ValidationError):
                    pass
                else:
                    self._development_manifest = manifest
                    return
            await sleep(0.05)
        msg = f"The isolated widget dev servers did not start in time ({path})"
        raise RuntimeError(msg)

    def _cleanup_runtime_directory(self) -> None:
        if self._runtime_directory is not None:
            self._runtime_directory.cleanup()
            self._runtime_directory = None
