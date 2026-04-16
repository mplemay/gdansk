from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

from httpx import AsyncClient
from pydantic import ValidationError

from gdansk.manifest import GdanskManifest, WidgetManifest
from gdansk.metadata import Metadata  # noqa: TC001 (MCP validate_call evaluates render_widget_page annotations)
from gdansk.render import render_template
from gdansk.utils import join_url, join_url_path

if TYPE_CHECKING:
    from gdansk.vite import Vite


class ShipContext:
    def __init__(
        self,
        views: Path,
        *,
        assets: str,
        base_url: str | None = None,
        vite: Vite,
        client: AsyncClient | None = None,
    ) -> None:
        self._assets_dir: Final[str] = assets
        self._base_url: Final[str | None] = base_url
        self._client: Final[AsyncClient] = client or AsyncClient()
        self._vite: Final[Vite] = vite
        self._views: Final[Path] = views

        self._vite.bind_runtime(cwd=views, client=self._client)

        self._active = False
        self._dev = False
        self._manifest: GdanskManifest | None = None

    def __call__(self, *, watch: bool | None) -> _ShipContextSession:
        return _ShipContextSession(_ctx=self, _watch=watch)

    def _session_begin(self, *, watch: bool | None) -> None:
        if self._active:
            msg = "The frontend runtime context is already active"
            raise RuntimeError(msg)
        self._active = True
        try:
            self._dev = watch is True
            match watch:
                case False | None:
                    self._manifest = self._load_manifest()
                case True:
                    pass
        except Exception:
            self._active = False
            self._dev = False
            self._manifest = None
            raise

    def _session_end(self) -> None:
        self._manifest = None
        self._dev = False
        self._active = False

    async def render_widget_page(self, *, metadata: Metadata | None, widget_key: str) -> str:
        body = ""
        head: list[str] = []
        runtime_origin: str | None = None

        if self._dev:
            runtime_origin = self._vite.require_origin()
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


@dataclass(slots=True, kw_only=True)
class _ShipContextSession:
    _ctx: ShipContext
    _watch: bool | None

    async def __aenter__(self) -> None:
        self._ctx._session_begin(watch=self._watch)  # noqa: SLF001

    async def __aexit__(self, _exc_type: object, _exc: BaseException | None, _tb: object) -> None:
        self._ctx._session_end()  # noqa: SLF001
