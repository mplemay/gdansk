from __future__ import annotations

from typing import Any, Final, cast

from pydantic import TypeAdapter
from starlette.responses import HTMLResponse, JSONResponse, Response

type InertiaResponse = HTMLResponse | JSONResponse | Response

_JSON_ADAPTER: Final[TypeAdapter[Any]] = TypeAdapter(Any)
_ERRORS_SESSION_KEY: Final[str] = "_gdansk_inertia_errors"
_FLASH_SESSION_KEY: Final[str] = "_gdansk_inertia_flash"
_PAGE_DEV_ENTRY: Final[str] = "/@gdansk/pages/app.tsx"
_PRESERVE_FRAGMENT_SESSION_KEY: Final[str] = "_gdansk_inertia_preserve_fragment"
_REQUIRED_V3_PAGE_KEYS: Final[frozenset[str]] = frozenset({"component", "flash", "props", "url", "version"})
_CLIENT_OWNED_V3_PAGE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "initialDeferredProps",
        "optimisticUpdatedAt",
        "rememberedState",
    },
)
_UNSUPPORTED_3X_PAGE_KEYS: Final[frozenset[str]] = frozenset({"rescuedProps"})
_V3_OPTIONAL_BOOLEAN_PAGE_KEYS: Final[tuple[str, ...]] = ("clearHistory", "preserveFragment", "encryptHistory")


def _validate_v3_page_payload(page: dict[str, Any]) -> None:
    if missing := _REQUIRED_V3_PAGE_KEYS.difference(page):
        msg = f"Inertia v3 page payload is missing required field(s): {', '.join(sorted(missing))}"
        raise RuntimeError(msg)

    if forbidden := (_CLIENT_OWNED_V3_PAGE_KEYS | _UNSUPPORTED_3X_PAGE_KEYS).intersection(page):
        msg = f"Inertia v3 page payload includes client-owned field(s): {', '.join(sorted(forbidden))}"
        raise RuntimeError(msg)

    for key in _V3_OPTIONAL_BOOLEAN_PAGE_KEYS:
        if page.get(key) is False:
            msg = f'Inertia v3 optional boolean field "{key}" must be omitted unless enabled'
            raise RuntimeError(msg)

    props = page["props"]
    if not isinstance(props, dict):
        msg = "Inertia v3 page payload props must be an object"
        raise TypeError(msg)

    if "errors" not in props:
        msg = 'Inertia v3 page payload props must include "errors"'
        raise RuntimeError(msg)

    if "deferred" in props:
        msg = 'Inertia v3 page payload must not include client-owned "props.deferred"'
        raise RuntimeError(msg)


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
