from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from typing import TYPE_CHECKING, Annotated, Any, cast

from pydantic import AliasChoices, AliasPath, BaseModel, ConfigDict, Field, create_model

from gdansk.inertia.props import Prop, _as_once_prop

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

type SharedPropPayload[SharedPropsT: BaseModel] = SharedPropsT | BaseModel | Mapping[str, object] | None


class SharedPropsState[SharedPropsT: BaseModel]:
    def __init__(self, model_type: type[SharedPropsT] | None) -> None:
        self._model_type = model_type
        self._props: dict[str, Any] = {}

    @property
    def props(self) -> dict[str, Any]:
        return self._props

    def update(self, payload: SharedPropPayload[SharedPropsT] = None, /, **updates: object) -> None:
        self._props.update(self._normalize_update(payload, updates))

    def update_once(self, payload: SharedPropPayload[SharedPropsT] = None, /, **updates: object) -> None:
        shared_once = {
            key: value if isinstance(value, Prop) and value.once_enabled else _as_once_prop(value, key=key)
            for key, value in self._normalize_update(payload, updates).items()
        }
        self._props.update(shared_once)

    def _normalize_update(
        self,
        payload: SharedPropPayload[SharedPropsT],
        updates: Mapping[str, object],
    ) -> dict[str, Any]:
        data = self._payload_to_update(payload)
        data.update(updates)

        if not data or self._model_type is None:
            return data

        update = _shared_update_model(self._model_type).model_validate(data)
        return _model_to_props(update, exclude_unset=True)

    def _payload_to_update(self, payload: SharedPropPayload[SharedPropsT]) -> dict[str, Any]:
        if payload is None:
            return {}

        if isinstance(payload, BaseModel):
            if self._model_type is not None and not isinstance(payload, self._model_type):
                msg = f"Inertia shared props model updates must use the configured {self._model_type.__name__} model"
                raise TypeError(msg)

            return _model_to_props(payload, exclude_unset=True)

        if isinstance(payload, Mapping):
            return _mapping_to_update(payload)

        msg = "Inertia share() updates require a pydantic model, mapping, or keyword arguments"
        raise TypeError(msg)


def _mapping_to_update(payload: Mapping[str, object]) -> dict[str, Any]:
    update: dict[str, Any] = {}
    for key, value in payload.items():
        if not isinstance(key, str):
            msg = "Inertia shared props mapping updates must use string keys"
            raise TypeError(msg)

        update[key] = value

    return update


@cache
def _shared_update_model[SharedPropsT: BaseModel](model_type: type[SharedPropsT]) -> type[BaseModel]:
    fields: dict[str, Any] = {
        field_name: _shared_update_field(field_name, model_field)
        for field_name, model_field in model_type.model_fields.items()
    }
    return cast(
        "type[BaseModel]",
        create_model(
            f"{model_type.__name__}Update",
            __config__=ConfigDict(
                arbitrary_types_allowed=True,
                extra="forbid",
                populate_by_name=True,
            ),
            __module__=model_type.__module__,
            **fields,
        ),
    )


def _shared_update_field(field_name: str, model_field: FieldInfo) -> tuple[Any, Any]:
    annotation = model_field.annotation or Any
    if model_field.metadata:
        annotation = Annotated[annotation, *model_field.metadata]

    prop_key = _model_field_prop_key(field_name, model_field)
    return (
        annotation,
        Field(
            default=None,
            alias=prop_key,
            validation_alias=_validation_alias(field_name, model_field, prop_key),
            serialization_alias=prop_key,
        ),
    )


def _validation_alias(field_name: str, model_field: FieldInfo, prop_key: str) -> str | AliasPath | AliasChoices:
    aliases: list[str | AliasPath] = []
    seen: set[str] = set()

    def add(value: object) -> None:
        if value is None:
            return

        if isinstance(value, AliasChoices):
            for choice in value.choices:
                add(choice)
            return

        if not isinstance(value, str | AliasPath):
            return

        key = value if isinstance(value, str) else repr(value)
        if key in seen:
            return

        seen.add(key)
        aliases.append(value)

    add(field_name)
    add(model_field.alias)
    add(model_field.validation_alias)
    add(model_field.serialization_alias)
    add(prop_key)

    if len(aliases) == 1:
        return aliases[0]

    return AliasChoices(*aliases)


def _model_to_props(model: BaseModel, *, exclude_unset: bool = False) -> dict[str, Any]:
    props = model.model_dump(mode="python", by_alias=True, exclude_unset=exclude_unset)
    fields_set = model.model_fields_set if exclude_unset else type(model).model_fields.keys()

    for field_name, model_field in type(model).model_fields.items():
        if field_name not in fields_set:
            continue

        prop_key = _model_field_prop_key(field_name, model_field)
        if prop_key not in props:
            continue

        if isinstance(value := getattr(model, field_name), Prop):
            props[prop_key] = value

    return cast("dict[str, Any]", props)


def _model_field_prop_key(field_name: str, model_field: FieldInfo) -> str:
    alias = model_field.serialization_alias or model_field.alias
    return alias if isinstance(alias, str) else field_name


__all__ = ["SharedPropPayload", "SharedPropsState"]
