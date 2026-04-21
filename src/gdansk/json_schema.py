from __future__ import annotations

from copy import deepcopy
from typing import cast

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
type JsonSchema = dict[str, JsonValue]

_INTERNAL_REF_PREFIX = "#/$defs/"


def normalize_json_schema(schema: JsonSchema) -> JsonSchema:
    definitions = schema.get("$defs")
    local_definitions = cast("JsonSchema", definitions) if isinstance(definitions, dict) else {}
    normalized_definitions: dict[str, JsonSchema] = {}
    resolving: set[str] = set()

    normalized_schema = _normalize_node(
        schema,
        definitions=local_definitions,
        normalized_definitions=normalized_definitions,
        resolving=resolving,
    )
    normalized_schema = cast("JsonSchema", normalized_schema)

    if _contains_internal_refs(normalized_schema) and normalized_definitions:
        normalized_schema["$defs"] = cast(
            "JsonValue",
            {name: deepcopy(definition) for name, definition in normalized_definitions.items()},
        )

    return normalized_schema


def _normalize_node(
    node: JsonValue,
    *,
    definitions: JsonSchema,
    normalized_definitions: dict[str, JsonSchema],
    resolving: set[str],
) -> JsonValue:
    if isinstance(node, list):
        return [
            _normalize_node(
                item,
                definitions=definitions,
                normalized_definitions=normalized_definitions,
                resolving=resolving,
            )
            for item in node
        ]

    if not isinstance(node, dict):
        return node

    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith(_INTERNAL_REF_PREFIX):
        normalized_ref = _resolve_ref(
            ref,
            definitions=definitions,
            normalized_definitions=normalized_definitions,
            resolving=resolving,
        )
        sibling_keywords = cast(
            "JsonSchema",
            {
                key: _normalize_node(
                    value,
                    definitions=definitions,
                    normalized_definitions=normalized_definitions,
                    resolving=resolving,
                )
                for key, value in node.items()
                if key not in {"$defs", "$ref"}
            },
        )
        return cast("JsonSchema", normalized_ref | sibling_keywords)

    return cast(
        "JsonSchema",
        {
            key: _normalize_node(
                value,
                definitions=definitions,
                normalized_definitions=normalized_definitions,
                resolving=resolving,
            )
            for key, value in node.items()
            if key != "$defs"
        },
    )


def _resolve_ref(
    ref: str,
    *,
    definitions: JsonSchema,
    normalized_definitions: dict[str, JsonSchema],
    resolving: set[str],
) -> JsonSchema:
    if not ref.startswith(_INTERNAL_REF_PREFIX):
        return {"$ref": ref}

    definition_name = ref.removeprefix(_INTERNAL_REF_PREFIX)
    if definition_name in normalized_definitions:
        return deepcopy(normalized_definitions[definition_name])

    definition = definitions.get(definition_name)
    if not isinstance(definition, dict):
        return {"$ref": ref}

    if definition_name in resolving:
        return {"$ref": ref}

    resolving.add(definition_name)
    try:
        normalized_definition = _normalize_node(
            cast("JsonSchema", definition),
            definitions=definitions,
            normalized_definitions=normalized_definitions,
            resolving=resolving,
        )
    finally:
        resolving.remove(definition_name)

    normalized_definition = cast("JsonSchema", normalized_definition)
    normalized_definitions[definition_name] = normalized_definition
    return deepcopy(normalized_definition)


def _contains_internal_refs(node: JsonValue) -> bool:
    if isinstance(node, list):
        return any(_contains_internal_refs(item) for item in node)

    if not isinstance(node, dict):
        return False

    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith(_INTERNAL_REF_PREFIX):
        return True

    return any(_contains_internal_refs(value) for value in node.values())
