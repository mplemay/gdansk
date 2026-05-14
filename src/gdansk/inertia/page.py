from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

from pydantic import BaseModel
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from gdansk.inertia.props import Prop, ScrollConfig
from gdansk.inertia.shared import SharedPropPayload, SharedPropsState
from gdansk.inertia.utils import (
    _ERRORS_SESSION_KEY,
    _FLASH_SESSION_KEY,
    _JSON_ADAPTER,
    _PRESERVE_FRAGMENT_SESSION_KEY,
    InertiaResponse,
    _dedupe,
    _exclude_nested,
    _get_object_path,
    _join_prop_path,
    _matching_paths,
    _select_nested,
    _validate_v3_page_payload,
)
from gdansk.utils import maybe_awaitable

if TYPE_CHECKING:
    from collections.abc import Callable, MutableMapping

    from starlette.requests import Request

    from gdansk.inertia.core import InertiaApp
    from gdansk.metadata import Metadata
    from gdansk.utils import MaybeAwaitable


class OnceProp(TypedDict):
    expiresAt: int | None
    prop: str


class ScrollProp(TypedDict):
    currentPage: Any
    nextPage: Any
    pageName: str
    previousPage: Any
    reset: bool


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


class InertiaPage[SharedPropsT: BaseModel]:
    def __init__(self, *, app: InertiaApp[SharedPropsT], request: Request) -> None:
        self._app = app
        self._clear_history_requested = False
        self._encrypt_history_enabled = app.default_encrypt_history
        self._local_flash: dict[str, Any] = {}
        self._request = request
        self._shared_props = SharedPropsState(app.shared_props_model)

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

    async def _render(
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

    def share(self, props: SharedPropPayload[SharedPropsT] = None, /, **updates: object) -> None:
        self._shared_props.update(props, **updates)

    def share_once(self, props: SharedPropPayload[SharedPropsT] = None, /, **updates: object) -> None:
        self._shared_props.update_once(props, **updates)

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
        _validate_v3_page_payload(page)

        return cast("dict[str, Any]", _JSON_ADAPTER.dump_python(page, mode="json"))

    async def _evaluate(self, value: object) -> object:
        if isinstance(value, Prop):
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
        merged = {**self._shared_props.props, **props}
        result = ResolvedPageData(
            shared_props=[key for key in self._shared_props.props if key not in props],
        )
        partial = self._is_partial_reload(component=component)
        only_keys = self._only_keys()
        except_keys = self._except_keys()
        reset_keys = self._reset_keys()
        except_once_keys = self._except_once_keys()
        merge_intent = self._merge_intent()

        for key, value in merged.items():
            page_prop = value if isinstance(value, Prop) else None
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
        page_prop: Prop[Any],
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
        page_prop: Prop[Any] | None,
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


__all__ = ["InertiaPage"]
