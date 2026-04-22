from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, cast

from gdansk._schema import JsonSchema, to_strict_schema

if TYPE_CHECKING:
    from collections.abc import Iterator


def _iter_schema_nodes(schema: object) -> Iterator[JsonSchema]:
    if not isinstance(schema, dict):
        return

    schema_dict = cast("JsonSchema", schema)
    yield schema_dict

    for key in ("$defs", "definitions", "properties"):
        yield from _iter_mapping_nodes(schema_dict, key=key)

    if isinstance(items := schema_dict.get("items"), dict):
        yield from _iter_schema_nodes(items)

    for key in ("anyOf", "allOf"):
        yield from _iter_sequence_nodes(schema_dict, key=key)


def _iter_mapping_nodes(schema: JsonSchema, *, key: str) -> Iterator[JsonSchema]:
    if isinstance(entries := schema.get(key), dict):
        for value in cast("dict[str, object]", entries).values():
            yield from _iter_schema_nodes(value)


def _iter_sequence_nodes(schema: JsonSchema, *, key: str) -> Iterator[JsonSchema]:
    if isinstance(entries := schema.get(key), list):
        for value in entries:
            yield from _iter_schema_nodes(value)


def test_to_strict_schema_does_not_mutate_input() -> None:
    schema = {
        "$defs": {
            "Location": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                    },
                },
            },
        },
        "type": "object",
        "properties": {
            "location": {
                "$ref": "#/$defs/Location",
                "description": "Location filters.",
            },
            "name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
            },
        },
    }

    original = deepcopy(schema)

    _ = to_strict_schema(schema)

    assert schema == original


def test_to_strict_schema_adds_additional_properties_and_required_recursively() -> None:
    schema = {
        "$defs": {
            "Location": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "radius": {"type": "integer", "default": 10},
                },
            },
        },
        "type": "object",
        "properties": {
            "filters": {
                "type": "object",
                "properties": {
                    "location": {"$ref": "#/$defs/Location"},
                },
            },
        },
    }

    strict_schema = to_strict_schema(schema)

    assert strict_schema["additionalProperties"] is False
    assert strict_schema["required"] == ["filters"]
    assert strict_schema["properties"]["filters"]["additionalProperties"] is False
    assert strict_schema["properties"]["filters"]["required"] == ["location"]
    assert strict_schema["$defs"]["Location"]["additionalProperties"] is False
    assert strict_schema["$defs"]["Location"]["required"] == ["city", "radius"]


def test_to_strict_schema_recurses_through_arrays_and_any_of() -> None:
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                    },
                },
            },
            "choice": {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"},
                        },
                    },
                    {
                        "type": "object",
                        "properties": {
                            "postal_code": {"type": "string"},
                        },
                    },
                ],
            },
        },
    }

    strict_schema = to_strict_schema(schema)

    array_item = strict_schema["properties"]["items"]["items"]
    assert array_item["additionalProperties"] is False
    assert array_item["required"] == ["name"]

    variants = strict_schema["properties"]["choice"]["anyOf"]
    assert variants[0]["additionalProperties"] is False
    assert variants[0]["required"] == ["city"]
    assert variants[1]["additionalProperties"] is False
    assert variants[1]["required"] == ["postal_code"]


def test_to_strict_schema_removes_null_defaults_and_preserves_non_null_defaults() -> None:
    schema = {
        "type": "object",
        "properties": {
            "name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
            },
            "radius": {
                "type": "integer",
                "default": 10,
            },
        },
    }

    strict_schema = to_strict_schema(schema)

    assert "default" not in strict_schema["properties"]["name"]
    assert strict_schema["properties"]["radius"]["default"] == 10


def test_to_strict_schema_inlines_refs_with_sibling_keys_and_keeps_pure_refs() -> None:
    schema = {
        "$defs": {
            "Location": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                },
            },
        },
        "type": "object",
        "properties": {
            "pure_ref": {"$ref": "#/$defs/Location"},
            "described_ref": {
                "$ref": "#/$defs/Location",
                "description": "Expanded location.",
            },
        },
    }

    strict_schema = to_strict_schema(schema)

    assert strict_schema["properties"]["pure_ref"] == {"$ref": "#/$defs/Location"}

    described_ref = strict_schema["properties"]["described_ref"]
    assert described_ref["description"] == "Expanded location."
    assert described_ref["type"] == "object"
    assert described_ref["additionalProperties"] is False
    assert described_ref["required"] == ["city"]
    assert "$ref" not in described_ref


def test_to_strict_schema_flattens_single_all_of() -> None:
    schema = {
        "type": "object",
        "properties": {
            "location": {
                "allOf": [
                    {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"},
                        },
                    },
                ],
            },
        },
    }

    strict_schema = to_strict_schema(schema)

    location = strict_schema["properties"]["location"]
    assert "allOf" not in location
    assert location["type"] == "object"
    assert location["additionalProperties"] is False
    assert location["required"] == ["city"]


def test_to_strict_schema_never_leaves_ref_nodes_with_sibling_keys() -> None:
    schema = {
        "$defs": {
            "Wrapper": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                },
            },
        },
        "type": "object",
        "properties": {
            "location": {
                "$ref": "#/$defs/Wrapper",
                "description": "Location wrapper.",
            },
        },
    }

    strict_schema = to_strict_schema(schema)

    for node in _iter_schema_nodes(strict_schema):
        if "$ref" in node:
            assert list(node.keys()) == ["$ref"]
