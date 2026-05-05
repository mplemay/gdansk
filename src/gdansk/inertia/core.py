from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import wraps
from hashlib import sha256
from inspect import Parameter, Signature, iscoroutinefunction, signature
from json import JSONDecodeError, dumps, loads
from typing import TYPE_CHECKING, Any, Final, TypedDict, cast, overload

from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import Response

from gdansk.inertia.page import InertiaPage
from gdansk.inertia.page_types import (
    PageTypeRoute,
    infer_page_props_model,
    normalize_page_props_model,
    write_page_type_modules,
)
from gdansk.inertia.props import Prop
from gdansk.inertia.utils import _PAGE_DEV_ENTRY, InertiaResponse
from gdansk.metadata import Metadata, merge_metadata
from gdansk.render import render_template
from gdansk.utils import join_url

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic.fields import FieldInfo

    from gdansk.core import Ship
    from gdansk.inertia.config import Inertia

type PageRouteResult = BaseModel | Mapping[str, object] | InertiaResponse | None
type PageRouteHandler = Callable[..., PageRouteResult | Awaitable[PageRouteResult]]
type PageRouteDecorator = Callable[[PageRouteHandler], Callable[..., object]]


class ViteManifestEntry(TypedDict, total=False):
    css: list[str]
    file: str
    imports: list[str]
    isEntry: bool
    src: str


@dataclass(slots=True, kw_only=True, frozen=True)
class PageAssets:
    css: list[str]
    script: str


class InertiaApp[SharedPropsT: BaseModel]:
    def __init__(
        self,
        *,
        ship: Ship[SharedPropsT],
        config: Inertia[SharedPropsT],
    ) -> None:
        self._default_encrypt_history: Final[bool] = config.encrypt_history
        self._page_type_routes: list[PageTypeRoute] = []
        self._root_id: Final[str] = config.id
        self._shared_props_model: Final[type[SharedPropsT] | None] = config.props
        self._ship: Final[Ship[SharedPropsT]] = ship
        self._version_override: Final[str | None] = config.version

    @property
    def root_id(self) -> str:
        return self._root_id

    @property
    def version_override(self) -> str | None:
        return self._version_override

    @property
    def default_encrypt_history(self) -> bool:
        return self._default_encrypt_history

    @property
    def shared_props_model(self) -> type[SharedPropsT] | None:
        return self._shared_props_model

    @overload
    def page(
        self,
        *,
        metadata: Metadata | None = None,
        props: type[BaseModel] | None = None,
        shared: type[BaseModel] | None = None,
    ) -> PageRouteDecorator: ...

    @overload
    def page(
        self,
        component: str,
        *,
        metadata: Metadata | None = None,
        props: type[BaseModel] | None = None,
        shared: type[BaseModel] | None = None,
    ) -> PageRouteDecorator: ...

    def page(
        self,
        component: str | None = None,
        *,
        metadata: Metadata | None = None,
        props: type[BaseModel] | None = None,
        shared: type[BaseModel] | None = None,
    ) -> PageRouteDecorator:
        normalized_component = self.normalize_component(component) if component is not None else None
        normalized_props_model = normalize_page_props_model(props, name="route")
        normalized_shared_model = normalize_page_props_model(shared, name="shared")

        def decorator(func: PageRouteHandler) -> Callable[..., object]:
            props_model = normalized_props_model or infer_page_props_model(func)

            @wraps(func)
            async def wrapper(
                *args: object,
                _gdansk_inertia_request: Request,
                **kwargs: object,
            ) -> InertiaResponse:
                page = self._route_page(
                    args=args,
                    kwargs=kwargs,
                    request=_gdansk_inertia_request,
                )
                result = await _execute_maybe_sync_func(func, *args, **kwargs)
                if isinstance(result, Response):
                    return result

                component_key = (
                    normalized_component
                    if normalized_component is not None
                    else self._component_from_request(_gdansk_inertia_request)
                )
                return await page._render(  # noqa: SLF001
                    component_key,
                    _route_result_to_props(result),
                    metadata=metadata,
                )

            decorated = _append_to_signature(
                wrapper,
                Parameter(
                    "_gdansk_inertia_request",
                    Parameter.KEYWORD_ONLY,
                    annotation=Request,
                ),
                return_annotation=Response,
            )
            self._page_type_routes.append(
                PageTypeRoute(
                    component=normalized_component,
                    endpoint=decorated,
                    props_model=props_model,
                    shared_model=normalized_shared_model,
                ),
            )
            return decorated

        return decorator

    @classmethod
    def _component_from_request(cls, request: Request) -> str:
        route = request.scope.get("route")
        route_path = getattr(route, "path", None)
        if isinstance(route_path, str) and route_path.strip():
            return cls.normalize_component(route_path)

        return cls.normalize_component(request.url.path)

    def _route_page(
        self,
        *,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        request: Request,
    ) -> InertiaPage[SharedPropsT]:
        pages = [value for value in (*args, *kwargs.values()) if isinstance(value, InertiaPage)]
        if len(pages) > 1:
            msg = "Inertia page decorators accept at most one InertiaPage dependency"
            raise RuntimeError(msg)

        if not pages:
            return InertiaPage(app=self, request=request)

        page = pages[0]
        if page._app is not self:  # noqa: SLF001
            msg = "Inertia page decorator received an InertiaPage from a different Inertia app"
            raise RuntimeError(msg)

        if page._request.scope is not request.scope:  # noqa: SLF001
            msg = "Inertia page decorator received an InertiaPage for a different request"
            raise RuntimeError(msg)

        return page

    def generate_page_types(self, *, app: object, output_root: Path, legacy_output_path: Path | None = None) -> None:
        write_page_type_modules(
            app=app,
            output_root=output_root,
            routes=self._page_type_routes,
            shared_props_model=self._shared_props_model,
            legacy_output_path=legacy_output_path,
        )

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


def _append_to_signature(
    func: Callable[..., object],
    *params: Parameter,
    return_annotation: object = Signature.empty,
) -> Callable[..., object]:
    base_signature = signature(func, eval_str=True)
    base_params = tuple(base_signature.parameters.values())
    insert_at = next(
        (index for index, param in enumerate(base_params) if param.kind == Parameter.VAR_KEYWORD),
        len(base_params),
    )
    cast("Any", func).__signature__ = base_signature.replace(
        parameters=(*base_params[:insert_at], *params, *base_params[insert_at:]),
        return_annotation=return_annotation,
    )
    return func


async def _execute_maybe_sync_func(func: Callable[..., object], *args: object, **kwargs: object) -> object:
    if iscoroutinefunction(func):
        async_func = cast("Callable[..., Awaitable[object]]", func)
        return await async_func(*args, **kwargs)

    return await run_in_threadpool(func, *args, **kwargs)


def _route_result_to_props(result: object) -> dict[str, Any]:
    if result is None:
        return {}

    if isinstance(result, BaseModel):
        return _model_to_props(result)

    if isinstance(result, Mapping):
        props: dict[str, Any] = {}
        for key, value in result.items():
            if not isinstance(key, str):
                msg = "Inertia page decorator mapping results must use string keys"
                raise TypeError(msg)
            props[key] = value

        return props

    msg = "Inertia page decorators require routes to return a pydantic model, mapping, response, or None"
    raise TypeError(msg)


def _model_to_props(model: BaseModel) -> dict[str, Any]:
    props = model.model_dump(mode="python", by_alias=True)

    for field_name, model_field in type(model).model_fields.items():
        prop_key = _model_field_prop_key(field_name, model_field)
        if prop_key not in props:
            continue

        if isinstance(value := getattr(model, field_name), Prop):
            props[prop_key] = value

    return props


def _model_field_prop_key(field_name: str, model_field: FieldInfo) -> str:
    alias = model_field.serialization_alias or model_field.alias
    return alias if isinstance(alias, str) else field_name


__all__ = ["InertiaApp", "PageRouteDecorator", "PageRouteHandler", "PageRouteResult"]
