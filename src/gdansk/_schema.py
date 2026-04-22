from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

_MISSING = object()
type JsonSchema = dict[str, Any]


def to_strict_schema(schema: JsonSchema) -> JsonSchema:
    root = deepcopy(schema)
    return _ensure_strict_schema(root, root=root)


def _ensure_strict_schema(
    json_schema: object,
    *,
    root: JsonSchema,
) -> JsonSchema:
    schema = _require_schema(json_schema)
    _normalize_definitions(schema, root=root)
    _normalize_object(schema, root=root)
    _normalize_items(schema, root=root)
    _normalize_variants(schema, key="anyOf", root=root)
    _normalize_all_of(schema, root=root)
    _remove_null_default(schema)

    if _should_inline_ref(schema):
        return _inline_ref_with_siblings(schema, root=root)

    return schema


def _require_schema(json_schema: object) -> JsonSchema:
    if not isinstance(json_schema, dict):
        msg = f"Expected a dictionary schema, got {type(json_schema).__name__}"
        raise TypeError(msg)

    return cast("JsonSchema", json_schema)


def _normalize_definitions(schema: JsonSchema, *, root: JsonSchema) -> None:
    for key in ("$defs", "definitions"):
        if not isinstance(entries := schema.get(key), dict):
            continue

        for child in cast("dict[str, object]", entries).values():
            _ensure_strict_schema(child, root=root)


def _normalize_object(schema: JsonSchema, *, root: JsonSchema) -> None:
    if schema.get("type") == "object" and "additionalProperties" not in schema:
        schema["additionalProperties"] = False

    if not isinstance(properties := schema.get("properties"), dict):
        return

    property_map = cast("dict[str, object]", properties)
    schema["required"] = list(property_map.keys())
    schema["properties"] = {
        key: _ensure_strict_schema(property_schema, root=root) for key, property_schema in property_map.items()
    }


def _normalize_items(schema: JsonSchema, *, root: JsonSchema) -> None:
    if isinstance(items := schema.get("items"), dict):
        schema["items"] = _ensure_strict_schema(items, root=root)


def _normalize_variants(schema: JsonSchema, *, key: str, root: JsonSchema) -> None:
    if isinstance(variants := schema.get(key), list):
        schema[key] = [_ensure_strict_schema(variant, root=root) for variant in variants]


def _normalize_all_of(schema: JsonSchema, *, root: JsonSchema) -> None:
    if not isinstance(all_of := schema.get("allOf"), list):
        return

    if len(all_of) == 1:
        schema.update(_ensure_strict_schema(all_of[0], root=root))
        schema.pop("allOf")
        return

    schema["allOf"] = [_ensure_strict_schema(entry, root=root) for entry in all_of]


def _remove_null_default(schema: JsonSchema) -> None:
    if schema.get("default", _MISSING) is None:
        schema.pop("default")


def _should_inline_ref(schema: JsonSchema) -> bool:
    return "$ref" in schema and _has_more_than_n_keys(schema, 1)


def _inline_ref_with_siblings(schema: JsonSchema, *, root: JsonSchema) -> JsonSchema:
    ref = schema["$ref"]
    if not isinstance(ref, str):
        msg = f"Expected string $ref, got {type(ref).__name__}"
        raise TypeError(msg)

    resolved = _resolve_ref(root=root, ref=ref)
    if not isinstance(resolved, dict):
        msg = f"Expected $ref {ref} to resolve to a dictionary schema"
        raise TypeError(msg)

    resolved_schema = cast("JsonSchema", resolved)
    schema.update({**resolved_schema, **schema})
    schema.pop("$ref")
    return _ensure_strict_schema(schema, root=root)


def _resolve_ref(*, root: JsonSchema, ref: str) -> object:
    if not ref.startswith("#/"):
        msg = f"Unexpected $ref format {ref!r}"
        raise ValueError(msg)

    resolved: object = root
    for key in ref[2:].split("/"):
        if not isinstance(resolved, dict):
            msg = f"Encountered a non-dictionary entry while resolving {ref!r}"
            raise TypeError(msg)
        resolved = cast("JsonSchema", resolved)[key]

    return resolved


def _has_more_than_n_keys(obj: JsonSchema, n: int) -> bool:
    return len(obj) > n
