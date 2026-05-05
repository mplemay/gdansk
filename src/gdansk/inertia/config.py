from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, kw_only=True, frozen=True)
class Inertia:
    id: str = "app"
    version: str | None = None
    encrypt_history: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _normalize_inertia_id(self.id))


def _normalize_inertia_id(id_value: str) -> str:
    if not (cleaned := id_value.strip()):
        msg = "The Inertia id must not be empty"
        raise ValueError(msg)

    return cleaned


__all__ = ["Inertia"]
