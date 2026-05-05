from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import wraps
from hashlib import sha256
from inspect import Parameter, Signature, iscoroutinefunction, signature
from json import JSONDecodeError, dumps, loads
from typing import TYPE_CHECKING, Any, Final, Literal, Self, TypedDict, cast, overload

from pydantic import BaseModel, TypeAdapter
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from gdansk.metadata import Metadata, merge_metadata
from gdansk.render import render_template
from gdansk.utils import MaybeAwaitable, join_url, maybe_awaitable

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

    from gdansk.core import Ship

type InertiaResponse = HTMLResponse | JSONResponse | Response
type PageRouteDecorator = Callable[[Callable[..., object]], Callable[..., object]]
type RawExpiration = datetime | timedelta | int

_JSON_ADAPTER: Final[TypeAdapter[Any]] = TypeAdapter(Any)
_ERRORS_SESSION_KEY: Final[str] = "_gdansk_inertia_errors"
_FLASH_SESSION_KEY: Final[str] = "_gdansk_inertia_flash"
_MISSING_PROP_VALUE: Final = object()
_PAGE_DEV_ENTRY: Final[str] = "/@gdansk/pages/app.tsx"
_PRESERVE_FRAGMENT_SESSION_KEY: Final[str] = "_gdansk_inertia_preserve_fragment"


class ViteManifestEntry(TypedDict, total=False):
    css: list[str]
    file: str
    imports: list[str]
    isEntry: bool
    src: str


class OnceProp(TypedDict):
    expiresAt: int | None
    prop: str


class ScrollProp(TypedDict):
    currentPage: Any
    nextPage: Any
    pageName: str
    previousPage: Any
    reset: bool


@dataclass(slots=True, kw_only=True, frozen=True)
class MergeInstruction:
    mode: Literal["append", "deep", "prepend"]
    match_on: tuple[str, ...] = ()
    path: str = ""


@dataclass(slots=True, kw_only=True, frozen=True)
class ScrollConfig:
    current_page_path: str
    items_path: str
    next_page_path: str
    page_name: str
    previous_page_path: str


@dataclass(slots=True, kw_only=True, frozen=True)
class PageProp:
    value: Any
    always_include: bool = False
    deferred_group: str | None = None
    include_on_initial: bool = True
    merge_instructions: tuple[MergeInstruction, ...] = field(default_factory=tuple)
    once_enabled: bool = False
    once_expires_at: RawExpiration | None = None
    once_fresh: bool = False
    once_key: str | None = None
    scroll_config: ScrollConfig | None = None

    def optional(self) -> Self:
        return replace(self, include_on_initial=False)

    def always(self) -> Self:
        return replace(self, always_include=True)

    def defer(self, *, group: str = "default") -> Self:
        return replace(
            self,
            deferred_group=_normalize_group(group),
            include_on_initial=False,
        )

    def once(self, key: str | None = None) -> Self:
        return replace(self, once_enabled=True, once_key=_normalize_once_key(key))

    def fresh(self, enabled: bool = True) -> Self:  # noqa: FBT001, FBT002
        return replace(self, once_enabled=True, once_fresh=enabled)

    def until(self, value: RawExpiration) -> Self:
        _resolve_once_expires_at(value)
        return replace(self, once_enabled=True, once_expires_at=value)

    def append(
        self,
        path: str | None = None,
        *,
        match_on: str | Sequence[str] | None = None,
    ) -> Self:
        return self._with_instruction(
            MergeInstruction(
                match_on=_normalize_match_on(match_on),
                mode="append",
                path=_normalize_prop_path(path or "", allow_empty=True, name="merge path"),
            ),
        )

    def prepend(
        self,
        path: str | None = None,
        *,
        match_on: str | Sequence[str] | None = None,
    ) -> Self:
        return self._with_instruction(
            MergeInstruction(
                match_on=_normalize_match_on(match_on),
                mode="prepend",
                path=_normalize_prop_path(path or "", allow_empty=True, name="merge path"),
            ),
        )

    def deep_merge(self, *, match_on: str | Sequence[str] | None = None) -> Self:
        return self._with_instruction(
            MergeInstruction(
                match_on=_normalize_match_on(match_on),
                mode="deep",
            ),
        )

    def scroll(
        self,
        *,
        current_page_path: str = "current_page",
        items_path: str = "data",
        next_page_path: str = "next_page",
        page_name: str = "page",
        previous_page_path: str = "previous_page",
    ) -> Self:
        if not (cleaned_page_name := page_name.strip()):
            msg = "The scroll page name must not be empty"
            raise ValueError(msg)

        return replace(
            self,
            scroll_config=ScrollConfig(
                current_page_path=_normalize_prop_path(
                    current_page_path,
                    allow_empty=True,
                    name="scroll current page path",
                ),
                items_path=_normalize_prop_path(items_path, allow_empty=True, name="scroll items path"),
                next_page_path=_normalize_prop_path(next_page_path, allow_empty=True, name="scroll next page path"),
                page_name=cleaned_page_name,
                previous_page_path=_normalize_prop_path(
                    previous_page_path,
                    allow_empty=True,
                    name="scroll previous page path",
                ),
            ),
        )

    def resolved_once_key(self, *, prop_name: str) -> str:
        return self.once_key or prop_name

    def resolved_once_expires_at(self) -> int | None:
        return _resolve_once_expires_at(self.once_expires_at)

    def _with_instruction(self, instruction: MergeInstruction) -> Self:
        instructions = (
            *(existing for existing in self.merge_instructions if existing.path != instruction.path),
            instruction,
        )
        return replace(self, merge_instructions=instructions)


@overload
def prop() -> PageProp: ...


@overload
def prop[T](value: T) -> PageProp: ...


def prop[T](value: T | object = _MISSING_PROP_VALUE) -> PageProp:
    if isinstance(value, PageProp):
        return value

    return PageProp(value=value)


@overload
def optional() -> PageProp: ...


@overload
def optional[T](value: T) -> PageProp: ...


def optional[T](value: T | object = _MISSING_PROP_VALUE) -> PageProp:
    return prop(value).optional()


@overload
def always() -> PageProp: ...


@overload
def always[T](value: T) -> PageProp: ...


def always[T](value: T | object = _MISSING_PROP_VALUE) -> PageProp:
    return prop(value).always()


@overload
def defer(*, group: str = "default") -> PageProp: ...


@overload
def defer[T](value: T, *, group: str = "default") -> PageProp: ...


def defer[T](value: T | object = _MISSING_PROP_VALUE, *, group: str = "default") -> PageProp:
    return prop(value).defer(group=group)


@overload
def once(*, key: str | None = None) -> PageProp: ...


@overload
def once[T](value: T, *, key: str | None = None) -> PageProp: ...


def once[T](value: T | object = _MISSING_PROP_VALUE, *, key: str | None = None) -> PageProp:
    return prop(value).once(key=key)


@overload
def merge(
    path: str | None = None,
    *,
    match_on: str | Sequence[str] | None = None,
) -> PageProp: ...


@overload
def merge[T](
    value: T,
    path: str | None = None,
    *,
    match_on: str | Sequence[str] | None = None,
) -> PageProp: ...


def merge[T](
    value: T | object = _MISSING_PROP_VALUE,
    path: str | None = None,
    *,
    match_on: str | Sequence[str] | None = None,
) -> PageProp:
    return prop(value).append(path, match_on=match_on)


@overload
def deep_merge(*, match_on: str | Sequence[str] | None = None) -> PageProp: ...


@overload
def deep_merge[T](value: T, *, match_on: str | Sequence[str] | None = None) -> PageProp: ...


def deep_merge[T](value: T | object = _MISSING_PROP_VALUE, *, match_on: str | Sequence[str] | None = None) -> PageProp:
    return prop(value).deep_merge(match_on=match_on)


@overload
def scroll(
    *,
    current_page_path: str = "current_page",
    items_path: str = "data",
    next_page_path: str = "next_page",
    page_name: str = "page",
    previous_page_path: str = "previous_page",
) -> PageProp: ...


@overload
def scroll[T](
    value: T,
    *,
    current_page_path: str = "current_page",
    items_path: str = "data",
    next_page_path: str = "next_page",
    page_name: str = "page",
    previous_page_path: str = "previous_page",
) -> PageProp: ...


def scroll[T](  # noqa: PLR0913
    value: T | object = _MISSING_PROP_VALUE,
    *,
    current_page_path: str = "current_page",
    items_path: str = "data",
    next_page_path: str = "next_page",
    page_name: str = "page",
    previous_page_path: str = "previous_page",
) -> PageProp:
    return prop(value).scroll(
        current_page_path=current_page_path,
        items_path=items_path,
        next_page_path=next_page_path,
        page_name=page_name,
        previous_page_path=previous_page_path,
    )


@dataclass(slots=True, kw_only=True, frozen=True)
class PageAssets:
    css: list[str]
    script: str


@dataclass(slots=True)
class ResolvedPageData:
    deep_merge_props: list[str] = field(default_factory=list)
    deferred_props: dict[str, list[str]] = field(default_factory=dict)
    match_props_on: list[str] = field(default_factory=list)
    merge_props: list[str] = field(default_factory=list)
    once_props: dict[str, OnceProp] = field(default_factory=dict)
    prepend_props: list[str] = field(default_factory=list)
    props: dict[str, Any] = field(default_factory=dict)
    scroll_props: dict[str, ScrollProp] = field(default_factory=dict)
    shared_props: list[str] = field(default_factory=list)


class InertiaApp:
    def __init__(
        self,
        *,
        ship: Ship,
        root_id: str,
        version: str | None,
        encrypt_history: bool,
    ) -> None:
        self._default_encrypt_history: Final[bool] = encrypt_history
        self._root_id: Final[str] = self._normalize_root_id(root_id)
        self._ship: Final[Ship] = ship
        self._version_override: Final[str | None] = version

    @property
    def root_id(self) -> str:
        return self._root_id

    @property
    def version_override(self) -> str | None:
        return self._version_override

    @property
    def default_encrypt_history(self) -> bool:
        return self._default_encrypt_history

    def page(
        self,
        component: str,
        *,
        metadata: Metadata | None = None,
    ) -> PageRouteDecorator:
        normalized_component = self.normalize_component(component)

        def decorator(func: Callable[..., object]) -> Callable[..., object]:
            @wraps(func)
            async def wrapper(
                *args: object,
                _gdansk_inertia_request: Request,
                **kwargs: object,
            ) -> InertiaResponse:
                result = await _execute_maybe_sync_func(func, *args, **kwargs)
                if isinstance(result, Response):
                    return result

                page = InertiaPage(app=self, request=_gdansk_inertia_request)
                return await page.render(
                    normalized_component,
                    _route_result_to_props(result),
                    metadata=metadata,
                )

            return _append_to_signature(
                wrapper,
                Parameter(
                    "_gdansk_inertia_request",
                    Parameter.KEYWORD_ONLY,
                    annotation=Request,
                ),
                return_annotation=Response,
            )

        return decorator

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
        self._clear_history_requested = False
        self._encrypt_history_enabled = app.default_encrypt_history
        self._local_flash: dict[str, Any] = {}
        self._request = request
        self._shared_props: dict[str, Any] = {}

    def back(self, *, preserve_fragment: bool = False) -> Response:
        return self.redirect(
            self._request.headers.get("referer", "/"),
            preserve_fragment=preserve_fragment,
        )

    def clear_history(self) -> None:
        self._clear_history_requested = True

    def encrypt_history(self, enabled: bool = True) -> None:  # noqa: FBT001, FBT002
        self._encrypt_history_enabled = enabled

    def flash(self, **payload: object) -> None:
        if not payload:
            return

        self._local_flash.update(payload)
        if (session := self._session()) is not None:
            existing = session.get(_FLASH_SESSION_KEY, {})
            merged = dict(existing) if isinstance(existing, dict) else {}
            merged.update(payload)
            session[_FLASH_SESSION_KEY] = merged

    def location(self, url: str) -> Response:
        if not self._is_inertia_request():
            status_code = 307 if self._request.method == "GET" else 303
            return RedirectResponse(url=url, status_code=status_code)

        return Response(
            status_code=409,
            headers={
                "Vary": "X-Inertia",
                "X-Inertia-Location": url,
            },
        )

    def redirect(self, url: str, *, preserve_fragment: bool = False) -> Response:
        if self._is_inertia_request() and "#" in url:
            return Response(
                status_code=409,
                headers={
                    "Vary": "X-Inertia",
                    "X-Inertia-Redirect": url,
                },
            )

        if preserve_fragment:
            self._store_preserve_fragment()

        status_code = 307 if self._request.method == "GET" else 303
        return RedirectResponse(
            url=url,
            status_code=status_code,
            headers={"Vary": "X-Inertia"},
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

    def share_once(self, **props: object) -> None:
        shared_once = {
            key: (value if isinstance(value, PageProp) and value.once_enabled else once(value, key=key))
            for key, value in props.items()
        }
        self.share(**shared_once)

    async def _build_page(self, *, component: str, props: dict[str, Any]) -> dict[str, Any]:
        resolved = await self._resolve_props(component=component, props=props)
        resolved.props["errors"] = self._consume_errors()

        page: dict[str, Any] = {
            "component": component,
            "flash": self._consume_flash(),
            "props": resolved.props,
            "url": self._relative_url(),
            "version": self._app.version(),
        }
        self._apply_page_metadata(page=page, resolved=resolved)

        return cast("dict[str, Any]", _JSON_ADAPTER.dump_python(page, mode="json"))

    async def _evaluate(self, value: object) -> object:
        if isinstance(value, PageProp):
            value = value.value

        if callable(value):
            value = await maybe_awaitable(cast("Callable[[], MaybeAwaitable[object]]", value))()

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

    def _consume_preserve_fragment(self) -> bool:
        if (session := self._session()) is None:
            return False

        return bool(session.pop(_PRESERVE_FRAGMENT_SESSION_KEY, False))

    def _is_inertia_request(self) -> bool:
        return "X-Inertia" in self._request.headers

    def _is_partial_reload(self, *, component: str) -> bool:
        if not self._is_inertia_request():
            return False

        return self._requested_partial_component() == component and (
            bool(self._only_keys()) or bool(self._except_keys()) or bool(self._reset_keys())
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

    def _reset_keys(self) -> set[str]:
        return self._split_header("X-Inertia-Reset")

    def _except_once_keys(self) -> set[str]:
        return self._split_header("X-Inertia-Except-Once-Props")

    def _merge_intent(self) -> Literal["append", "prepend"] | None:
        raw = self._request.headers.get("X-Inertia-Infinite-Scroll-Merge-Intent", "").strip().lower()
        if raw in {"append", "prepend"}:
            return cast('Literal["append", "prepend"]', raw)

        return None

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
    ) -> ResolvedPageData:
        merged = {**self._shared_props, **props}
        result = ResolvedPageData(
            shared_props=[key for key in self._shared_props if key not in props],
        )
        partial = self._is_partial_reload(component=component)
        only_keys = self._only_keys()
        except_keys = self._except_keys()
        reset_keys = self._reset_keys()
        except_once_keys = self._except_once_keys()
        merge_intent = self._merge_intent()

        for key, value in merged.items():
            page_prop = value if isinstance(value, PageProp) else None
            direct_only, nested_only = _matching_paths(key, only_keys)
            direct_except, nested_except = _matching_paths(key, except_keys)
            explicitly_requested = direct_only or bool(nested_only)

            include = self._should_include_prop(
                page_prop=page_prop,
                partial=partial,
                only_keys=only_keys,
                except_keys=except_keys,
                explicitly_requested=explicitly_requested,
                explicitly_excluded=direct_except,
            )

            skip_due_once = False
            if page_prop and page_prop.once_enabled:
                once_key = page_prop.resolved_once_key(prop_name=key)
                expires_at = page_prop.resolved_once_expires_at()
                self._register_once_prop(result, once_key=once_key, prop_name=key, expires_at=expires_at)
                skip_due_once = (
                    once_key in except_once_keys
                    and not page_prop.once_fresh
                    and not explicitly_requested
                    and not self._once_expired(expires_at)
                )

            if include and not skip_due_once:
                resolved_value = await self._evaluate(value)
                filtered_value = self._filter_nested_value(
                    resolved_value,
                    direct_only=direct_only,
                    nested_only=nested_only,
                    nested_except=nested_except,
                )
                result.props[key] = filtered_value

                if page_prop and page_prop.scroll_config is not None:
                    result.scroll_props[key] = self._build_scroll_prop(
                        key=key,
                        value=resolved_value,
                        config=page_prop.scroll_config,
                        reset=key in reset_keys,
                    )

            if not partial and page_prop and page_prop.deferred_group is not None and not include:
                result.deferred_props.setdefault(page_prop.deferred_group, []).append(key)

            if page_prop is not None:
                self._collect_merge_metadata(
                    key=key,
                    page_prop=page_prop,
                    result=result,
                    reset=key in reset_keys,
                    merge_intent=merge_intent,
                )

        return result

    def _session(self) -> MutableMapping[str, Any] | None:
        try:
            return cast("MutableMapping[str, Any]", self._request.session)
        except AssertionError:
            return None

    def _split_header(self, name: str) -> set[str]:
        raw = self._request.headers.get(name, "")
        return {part.strip() for part in raw.split(",") if part.strip()}

    def _store_preserve_fragment(self) -> None:
        if (session := self._session()) is not None:
            session[_PRESERVE_FRAGMENT_SESSION_KEY] = True

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

    def _build_scroll_prop(
        self,
        *,
        key: str,
        value: object,
        config: ScrollConfig,
        reset: bool,
    ) -> ScrollProp:
        try:
            current_page = _get_object_path(value, config.current_page_path)
            next_page = _get_object_path(value, config.next_page_path)
            previous_page = _get_object_path(value, config.previous_page_path)
        except ValueError as exc:
            msg = f'The scroll metadata for "{key}" could not be resolved'
            raise ValueError(msg) from exc

        return ScrollProp(
            currentPage=current_page,
            nextPage=next_page,
            pageName=config.page_name,
            previousPage=previous_page,
            reset=reset,
        )

    def _apply_page_metadata(self, *, page: dict[str, Any], resolved: ResolvedPageData) -> None:
        metadata_values: tuple[tuple[str, object], ...] = (
            ("deepMergeProps", _dedupe(resolved.deep_merge_props)),
            ("deferredProps", resolved.deferred_props),
            ("matchPropsOn", _dedupe(resolved.match_props_on)),
            ("mergeProps", _dedupe(resolved.merge_props)),
            ("onceProps", resolved.once_props),
            ("prependProps", _dedupe(resolved.prepend_props)),
            ("scrollProps", resolved.scroll_props),
            ("sharedProps", resolved.shared_props),
        )
        page.update({key: value for key, value in metadata_values if value})

        flags = (
            ("clearHistory", self._clear_history_requested),
            ("preserveFragment", self._consume_preserve_fragment()),
            ("encryptHistory", self._encrypt_history_enabled),
        )
        for key, enabled in flags:
            if enabled:
                page[key] = True

    def _collect_merge_metadata(
        self,
        *,
        key: str,
        page_prop: PageProp,
        result: ResolvedPageData,
        reset: bool,
        merge_intent: Literal["append", "prepend"] | None,
    ) -> None:
        if reset:
            return

        for instruction in page_prop.merge_instructions:
            full_path = _join_prop_path(key, instruction.path)
            if instruction.mode == "append":
                result.merge_props.append(full_path)
                match_base = full_path
            elif instruction.mode == "prepend":
                result.prepend_props.append(full_path)
                match_base = full_path
            else:
                result.deep_merge_props.append(full_path)
                match_base = key

            for match_path in instruction.match_on:
                result.match_props_on.append(_join_prop_path(match_base, match_path))

        if page_prop.scroll_config is not None:
            target_path = _join_prop_path(key, page_prop.scroll_config.items_path)
            if merge_intent == "prepend":
                result.prepend_props.append(target_path)
            else:
                result.merge_props.append(target_path)

    def _filter_nested_value(
        self,
        value: object,
        *,
        direct_only: bool,
        nested_only: list[str],
        nested_except: list[str],
    ) -> object:
        if direct_only:
            return value

        filtered = value
        if nested_only:
            filtered = _select_nested(filtered, nested_only)
        if nested_except:
            filtered = _exclude_nested(filtered, nested_except)

        return filtered

    def _register_once_prop(
        self,
        result: ResolvedPageData,
        *,
        once_key: str,
        prop_name: str,
        expires_at: int | None,
    ) -> None:
        if (existing := result.once_props.get(once_key)) and existing["prop"] != prop_name:
            msg = f'The once prop key "{once_key}" is already registered for "{existing["prop"]}"'
            raise ValueError(msg)

        result.once_props[once_key] = OnceProp(expiresAt=expires_at, prop=prop_name)

    @staticmethod
    def _once_expired(expires_at: int | None) -> bool:
        if expires_at is None:
            return False

        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        return expires_at <= now_ms

    @staticmethod
    def _should_include_prop(  # noqa: PLR0913
        *,
        page_prop: PageProp | None,
        partial: bool,
        only_keys: set[str],
        except_keys: set[str],
        explicitly_requested: bool,
        explicitly_excluded: bool,
    ) -> bool:
        if partial:
            if page_prop and page_prop.always_include:
                return True
            if only_keys:
                return explicitly_requested
            if page_prop and not page_prop.include_on_initial:
                return False
            if except_keys:
                return not explicitly_excluded
            return True

        return page_prop.include_on_initial if page_prop else True


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
        markers = [metadata for metadata in model_field.metadata if isinstance(metadata, PageProp)]
        if not markers:
            continue

        prop_key = _model_field_prop_key(field_name, model_field)
        if prop_key not in props:
            continue

        props[prop_key] = _apply_page_prop_markers(props[prop_key], markers)

    return props


def _model_field_prop_key(field_name: str, model_field: FieldInfo) -> str:
    alias = model_field.serialization_alias or model_field.alias
    return alias if isinstance(alias, str) else field_name


def _apply_page_prop_markers(value: object, markers: Sequence[PageProp]) -> PageProp:
    result = prop(value)
    for marker in markers:
        result = _apply_page_prop_marker(result, marker)

    return result


def _apply_page_prop_marker(result: PageProp, marker: PageProp) -> PageProp:
    if marker.always_include:
        result = result.always()
    if marker.deferred_group is not None:
        result = result.defer(group=marker.deferred_group)
    elif not marker.include_on_initial:
        result = result.optional()
    if marker.once_enabled:
        result = result.once(key=marker.once_key)
    if marker.once_fresh:
        result = result.fresh()
    if marker.once_expires_at is not None:
        result = result.until(marker.once_expires_at)
    for instruction in marker.merge_instructions:
        result = result._with_instruction(instruction)  # noqa: SLF001
    if marker.scroll_config is not None:
        result = replace(result, scroll_config=marker.scroll_config)

    return result


def _build_path_tree(paths: list[str]) -> dict[str, dict[str, Any]]:
    tree: dict[str, dict[str, Any]] = {}
    for path in paths:
        node = tree
        for segment in path.split("."):
            node = node.setdefault(segment, {})

    return tree


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _exclude_nested(value: object, paths: list[str]) -> object:
    if not paths:
        return value

    tree = _build_path_tree(paths)
    return _exclude_with_tree(value, tree)


def _exclude_with_tree(value: object, tree: dict[str, dict[str, Any]]) -> object:
    if not tree:
        return value

    if isinstance(value, dict):
        mapping = cast("dict[str, Any]", value)
        result: dict[str, Any] = {}
        for key, item in mapping.items():
            if key not in tree:
                result[key] = item
                continue

            subtree = tree[key]
            if subtree:
                result[key] = _exclude_with_tree(item, subtree)

        return result

    if isinstance(value, list):
        return [_exclude_with_tree(item, tree) for item in value]

    return value


def _get_object_path(value: object, path: str) -> object:
    if not path:
        return value

    current = value
    for segment in path.split("."):
        if isinstance(current, dict):
            mapping = cast("dict[str, Any]", current)
            if segment not in mapping:
                msg = f'The path "{path}" does not exist'
                raise ValueError(msg)
            current = mapping[segment]
        elif isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if index >= len(current):
                msg = f'The path "{path}" does not exist'
                raise ValueError(msg)
            current = current[index]
        elif hasattr(current, segment):
            current = getattr(current, segment)
        else:
            msg = f'The path "{path}" does not exist'
            raise ValueError(msg)

    return current


def _join_prop_path(*parts: str) -> str:
    return ".".join(part for part in parts if part)


def _matching_paths(key: str, paths: set[str]) -> tuple[bool, list[str]]:
    direct = False
    nested: list[str] = []
    prefix = f"{key}."

    for path in paths:
        if path == key:
            direct = True
        elif path.startswith(prefix):
            nested.append(path.removeprefix(prefix))

    return direct, nested


def _normalize_group(group: str) -> str:
    if not (cleaned := group.strip()):
        msg = "The deferred prop group must not be empty"
        raise ValueError(msg)

    return cleaned


def _normalize_match_on(match_on: str | Sequence[str] | None) -> tuple[str, ...]:
    if match_on is None:
        return ()

    values = [match_on] if isinstance(match_on, str) else list(match_on)
    return tuple(_normalize_prop_path(value, name="match-on path") for value in values)


def _normalize_once_key(key: str | None) -> str | None:
    if key is None:
        return None

    if not (cleaned := key.strip()):
        msg = "The once prop key must not be empty"
        raise ValueError(msg)

    return cleaned


def _normalize_prop_path(path: str, *, allow_empty: bool = False, name: str) -> str:
    if not (cleaned := path.strip()):
        if allow_empty:
            return ""
        msg = f"The {name} must not be empty"
        raise ValueError(msg)

    parts = [segment.strip() for segment in cleaned.split(".")]
    if any(segment in {"", ".", ".."} for segment in parts):
        msg = f"The {name} must not contain empty or traversal segments"
        raise ValueError(msg)

    return ".".join(parts)


def _resolve_once_expires_at(value: RawExpiration | None) -> int | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        target = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    elif isinstance(value, timedelta):
        target = datetime.now(UTC) + value
    elif isinstance(value, int):
        target = datetime.now(UTC) + timedelta(seconds=value)
    else:
        msg = "The once prop expiration must be a datetime, timedelta, or integer second count"
        raise TypeError(msg)

    return int(target.timestamp() * 1000)


def _select_nested(value: object, paths: list[str]) -> object:
    if not paths:
        return value

    tree = _build_path_tree(paths)
    return _select_with_tree(value, tree)


def _select_with_tree(value: object, tree: dict[str, dict[str, Any]]) -> object:
    if not tree:
        return value

    if isinstance(value, dict):
        mapping = cast("dict[str, Any]", value)
        result: dict[str, Any] = {}
        for key, subtree in tree.items():
            if key in mapping:
                result[key] = _select_with_tree(mapping[key], subtree)

        return result

    if isinstance(value, list):
        return [_select_with_tree(item, tree) for item in value]

    return value


__all__ = [
    "_ERRORS_SESSION_KEY",
    "_FLASH_SESSION_KEY",
    "InertiaApp",
    "InertiaPage",
    "InertiaResponse",
    "PageProp",
    "always",
    "deep_merge",
    "defer",
    "merge",
    "once",
    "optional",
    "prop",
    "scroll",
]
