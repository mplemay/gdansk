from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(slots=True, kw_only=True, frozen=True)
class Inertia[SharedPropsT: BaseModel]:
    id: str = "app"
    version: str | None = None
    encrypt_history: bool = False
    props: type[SharedPropsT] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _normalize_inertia_id(self.id))
        object.__setattr__(self, "props", _normalize_shared_props_model(self.props))


def _normalize_inertia_id(id_value: str) -> str:
    if not (cleaned := id_value.strip()):
        msg = "The Inertia id must not be empty"
        raise ValueError(msg)

    return cleaned


def _normalize_shared_props_model[SharedPropsT: BaseModel](
    props: type[SharedPropsT] | None,
) -> type[SharedPropsT] | None:
    if props is None:
        return None

    if not isinstance(props, type) or not issubclass(props, BaseModel):
        msg = "The Inertia props model must be a pydantic BaseModel subclass"
        raise TypeError(msg)

    return props


__all__ = ["Inertia"]
