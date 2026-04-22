from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
from inspect import isawaitable
from json import JSONDecodeError, dumps, loads
from typing import TYPE_CHECKING, Any, Final, TypedDict, cast

from pydantic import TypeAdapter
from starlette.requests import Request  # noqa: TC002
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from gdansk.metadata import Metadata, merge_metadata
from gdansk.render import render_template
from gdansk.utils import join_url

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping

    from gdansk.core import Ship

type InertiaResponse = HTMLResponse | JSONResponse | Response

_JSON_ADAPTER: Final[TypeAdapter[Any]] = TypeAdapter(Any)
_ERRORS_SESSION_KEY: Final[str] = "_gdansk_inertia_errors"
_FLASH_SESSION_KEY: Final[str] = "_gdansk_inertia_flash"
_PAGE_DEV_ENTRY: Final[str] = "/@gdansk/pages/app.tsx"


class ViteManifestEntry(TypedDict, total=False):
    css: list[str]
    file: str
    imports: list[str]
    isEntry: bool
    src: str


@dataclass(slots=True, kw_only=True, frozen=True)
class PageProp:
    value: Any
    always: bool = False
    deferred_group: str | None = None
    include_on_initial: bool = True


def optional[T](value: T) -> PageProp:
    return PageProp(value=value, include_on_initial=False)


def always[T](value: T) -> PageProp:
    return PageProp(value=value, always=True)


def defer[T](value: T, *, group: str = "default") -> PageProp:
    if not (cleaned := group.strip()):
        msg = "The deferred prop group must not be empty"
        raise ValueError(msg)

    return PageProp(value=value, deferred_group=cleaned, include_on_initial=False)


@dataclass(slots=True, kw_only=True, frozen=True)
class PageAssets:
    css: list[str]
    script: str


class InertiaApp:
    def __init__(
        self,
        *,
        ship: Ship,
        root_id: str,
        version: str | None,
    ) -> None:
        self._root_id: Final[str] = self._normalize_root_id(root_id)
        self._ship: Final[Ship] = ship
        self._version_override: Final[str | None] = version

    @property
    def root_id(self) -> str:
        return self._root_id

    @property
    def version_override(self) -> str | None:
        return self._version_override

    @asynccontextmanager
    async def lifespan(self, *, watch: bool | None = False) -> AsyncIterator[None]:
        async with self._ship.frontend_session(watch=watch):
            if not self._ship.dev:
                self._resolve_assets()
            yield None

    def dependency(self) -> Callable[[Request], InertiaPage]:
        def dependency(request: Request) -> InertiaPage:
            return InertiaPage(app=self, request=request)

        return dependency

    def version(self) -> str | None:
        if self._version_override is not None:
            return self._version_override

        if self._ship.dev:
            return None

        path = self._ship.client_manifest_path
        if not path.is_file():
            msg = f"The frontend build did not produce a manifest at {path}"
            raise RuntimeError(msg)

        return sha256(path.read_bytes()).hexdigest()[:12]

    def render_html(self, *, metadata: Metadata | None, page: dict[str, Any]) -> str:
        assets = self._resolve_assets()
        body = (
            f'<script data-page="{self._root_id}" type="application/json">{self._serialize_page_data(page)}</script>'
            f'<div id="{self._root_id}"></div>'
        )
        head = [f'<link rel="stylesheet" href="{href}">' for href in assets.css]
        runtime_origin: str | None = None

        if self._ship.dev:
            runtime_origin = self._ship.require_vite_origin()
            scripts = [
                join_url(runtime_origin, "/@vite/client"),
                assets.script,
            ]
        else:
            scripts = [assets.script]

        return render_template(
            "page.html",
            body=body,
            dev=self._ship.dev,
            head=head,
            metadata=merge_metadata(self._ship.metadata, metadata),
            runtime_origin=runtime_origin,
            scripts=scripts,
        )

    def _resolve_assets(self) -> PageAssets:
        if self._ship.dev:
            runtime_origin = self._ship.require_vite_origin()
            return PageAssets(css=[], script=join_url(runtime_origin, _PAGE_DEV_ENTRY))

        manifest = self._load_client_manifest()
        entry = self._resolve_manifest_entry(manifest)
        css = [self._ship.asset_url(href) for href in self._collect_css(manifest, entry)]
        return PageAssets(css=css, script=self._ship.asset_url(entry["file"]))

    def _collect_css(
        self,
        manifest: dict[str, ViteManifestEntry],
        entry: ViteManifestEntry,
    ) -> list[str]:
        css: list[str] = []
        seen_css: set[str] = set()
        visited_entries: set[str] = set()

        def visit(chunk: ViteManifestEntry) -> None:
            file = chunk.get("file")
            if file is None or file in visited_entries:
                return

            visited_entries.add(file)

            for imported in chunk.get("imports", []):
                if imported_chunk := manifest.get(imported):
                    visit(imported_chunk)

            for href in chunk.get("css", []):
                if href in seen_css:
                    continue

                seen_css.add(href)
                css.append(href)

            return

        visit(entry)
        return css

    def _load_client_manifest(self) -> dict[str, ViteManifestEntry]:
        path = self._ship.client_manifest_path
        if not path.is_file():
            msg = f"The frontend build did not produce a manifest at {path}"
            raise RuntimeError(msg)

        try:
            manifest = loads(path.read_text(encoding="utf-8"))
        except JSONDecodeError as exc:
            msg = f"The frontend build produced an invalid manifest at {path}"
            raise RuntimeError(msg) from exc

        if not isinstance(manifest, dict):
            msg = f"The frontend build produced an invalid manifest at {path}"
            raise TypeError(msg)

        return cast("dict[str, ViteManifestEntry]", manifest)

    def _resolve_manifest_entry(self, manifest: dict[str, ViteManifestEntry]) -> ViteManifestEntry:
        entries = [chunk for chunk in manifest.values() if chunk.get("isEntry") and "file" in chunk]

        if len(entries) == 1:
            return entries[0]

        if len(entries) == 0:
            msg = "The frontend build manifest does not contain a page entry"
            raise RuntimeError(msg)

        msg = "The frontend build manifest must contain exactly one page entry"
        raise RuntimeError(msg)

    @staticmethod
    def _normalize_root_id(root_id: str) -> str:
        if not (cleaned := root_id.strip()):
            msg = "The Inertia root ID must not be empty"
            raise ValueError(msg)

        return cleaned

    @staticmethod
    def normalize_component(component: str) -> str:
        if not (cleaned := component.strip()):
            msg = "The Inertia component must not be empty"
            raise ValueError(msg)

        if cleaned == "/":
            return cleaned

        normalized = cleaned.strip("/")
        if not normalized:
            return "/"

        parts = normalized.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            msg = "The Inertia component must be '/' or a relative path without traversal segments"
            raise ValueError(msg)

        return "/".join(parts)

    @staticmethod
    def _serialize_page_data(page: dict[str, Any]) -> str:
        serialized = dumps(page, separators=(",", ":"), ensure_ascii=False)
        return (
            serialized.replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
        )


class InertiaPage:
    def __init__(self, *, app: InertiaApp, request: Request) -> None:
        self._app = app
        self._request = request
        self._local_flash: dict[str, Any] = {}
        self._shared_props: dict[str, Any] = {}

    def back(self) -> RedirectResponse:
        status_code = 307 if self._request.method == "GET" else 303
        return RedirectResponse(
            url=self._request.headers.get("referer", "/"),
            status_code=status_code,
            headers={"Vary": "X-Inertia"},
        )

    def flash(self, **payload: object) -> None:
        if not payload:
            return

        self._local_flash.update(payload)
        if (session := self._session()) is not None:
            existing = session.get(_FLASH_SESSION_KEY, {})
            merged = dict(existing) if isinstance(existing, dict) else {}
            merged.update(payload)
            session[_FLASH_SESSION_KEY] = merged

        return

    def location(self, url: str) -> Response:
        if not self._is_inertia_request():
            return RedirectResponse(url=url)

        return Response(
            status_code=409,
            headers={
                "Vary": "X-Inertia",
                "X-Inertia-Location": url,
            },
        )

    async def render(
        self,
        component: str,
        props: dict[str, Any] | None = None,
        *,
        metadata: Metadata | None = None,
    ) -> InertiaResponse:
        normalized_component = self._app.normalize_component(component)

        if response := self._version_conflict_response():
            return response

        page = await self._build_page(component=normalized_component, props=props or {})
        if self._is_inertia_request():
            return JSONResponse(
                content=page,
                headers={
                    "Vary": "X-Inertia",
                    "X-Inertia": "true",
                },
            )

        return HTMLResponse(
            content=self._app.render_html(metadata=metadata, page=page),
            headers={"Vary": "X-Inertia"},
        )

    def share(self, **props: object) -> None:
        self._shared_props.update(props)

    async def _build_page(self, *, component: str, props: dict[str, Any]) -> dict[str, Any]:
        resolved_props, deferred_props = await self._resolve_props(component=component, props=props)
        resolved_props["errors"] = self._consume_errors()

        page = {
            "component": component,
            "flash": self._consume_flash(),
            "props": resolved_props,
            "url": self._relative_url(),
            "version": self._app.version(),
        }
        if deferred_props:
            page["deferredProps"] = deferred_props

        return cast("dict[str, Any]", _JSON_ADAPTER.dump_python(page, mode="json"))

    async def _evaluate(self, value: object) -> object:
        if isinstance(value, PageProp):
            value = value.value

        if callable(value):
            value = cast("Callable[[], object]", value)()
            if isawaitable(value):
                value = await cast("Awaitable[object]", value)

        if isinstance(value, dict):
            return {key: await self._evaluate(item) for key, item in value.items()}

        if isinstance(value, list):
            return [await self._evaluate(item) for item in value]

        if isinstance(value, tuple):
            return [await self._evaluate(item) for item in value]

        return value

    def _consume_errors(self) -> dict[str, Any]:
        session_errors = self._pop_session_dict(_ERRORS_SESSION_KEY)
        return session_errors or {}

    def _consume_flash(self) -> dict[str, Any]:
        flash = self._pop_session_dict(_FLASH_SESSION_KEY)
        flash.update(self._local_flash)
        self._local_flash.clear()
        return flash

    def _is_inertia_request(self) -> bool:
        return "X-Inertia" in self._request.headers

    def _is_partial_reload(self, *, component: str) -> bool:
        if not self._is_inertia_request():
            return False

        return self._requested_partial_component() == component and (
            bool(self._only_keys()) or bool(self._except_keys())
        )

    def _requested_partial_component(self) -> str | None:
        if raw := self._request.headers.get("X-Inertia-Partial-Component"):
            try:
                return self._app.normalize_component(raw)
            except ValueError:
                return None

        return None

    def _only_keys(self) -> set[str]:
        return self._split_header("X-Inertia-Partial-Data")

    def _except_keys(self) -> set[str]:
        return self._split_header("X-Inertia-Partial-Except")

    def _pop_session_dict(self, key: str) -> dict[str, Any]:
        if (session := self._session()) is None:
            return {}

        value = session.pop(key, {})
        return dict(value) if isinstance(value, dict) else {}

    def _relative_url(self) -> str:
        path = self._request.url.path
        if query := self._request.url.query:
            return f"{path}?{query}"

        return path

    async def _resolve_props(
        self,
        *,
        component: str,
        props: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, list[str]] | None]:
        merged = {**self._shared_props, **props}
        resolved: dict[str, Any] = {}
        deferred: dict[str, list[str]] = {}
        partial = self._is_partial_reload(component=component)
        only_keys = self._only_keys()
        except_keys = self._except_keys()

        for key, value in merged.items():
            page_prop = value if isinstance(value, PageProp) else None

            if partial:
                if page_prop and page_prop.always:
                    include = True
                elif only_keys:
                    include = key in only_keys
                elif page_prop and not page_prop.include_on_initial:
                    include = False
                elif except_keys:
                    include = key not in except_keys
                else:
                    include = True
            else:
                include = page_prop.include_on_initial if page_prop else True

            if include:
                resolved[key] = await self._evaluate(value)
                continue

            if partial or not page_prop or page_prop.deferred_group is None:
                continue

            deferred.setdefault(page_prop.deferred_group, []).append(key)

        return resolved, deferred or None

    def _session(self) -> MutableMapping[str, Any] | None:
        try:
            return cast("MutableMapping[str, Any]", self._request.session)
        except AssertionError:
            return None

    def _split_header(self, name: str) -> set[str]:
        raw = self._request.headers.get(name, "")
        return {part.strip() for part in raw.split(",") if part.strip()}

    def _version_conflict_response(self) -> Response | None:
        if not self._is_inertia_request() or self._request.method != "GET":
            return None

        current_version = self._app.version()
        if current_version is None:
            return None

        requested_version = self._request.headers.get("X-Inertia-Version", current_version)
        if requested_version == current_version:
            return None

        return Response(
            status_code=409,
            headers={
                "Vary": "X-Inertia",
                "X-Inertia-Location": str(self._request.url),
            },
        )


__all__ = [
    "_ERRORS_SESSION_KEY",
    "_FLASH_SESSION_KEY",
    "InertiaApp",
    "InertiaPage",
    "InertiaResponse",
    "PageProp",
    "always",
    "defer",
    "optional",
]
