from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from gdansk.utils import MaybeAwaitable

type RawExpiration = datetime | timedelta | int
type SerializableProp = (
    None | bool | int | float | str | BaseModel | Mapping[str, SerializableProp] | Sequence[SerializableProp]
)
type PropSource[T] = T | Callable[[], MaybeAwaitable[T]]

_PROP_MODEL_CONFIG: Final[ConfigDict] = ConfigDict(
    arbitrary_types_allowed=True,
    extra="forbid",
    populate_by_name=True,
)


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


class Prop[T](BaseModel):
    model_config = _PROP_MODEL_CONFIG

    value: PropSource[T]
    always_include: bool = False
    deferred_group: str | None = None
    include_on_initial: bool = True
    merge_instructions: tuple[MergeInstruction, ...] = ()
    once_enabled: bool = False
    once_expires_at: RawExpiration | None = None
    once_fresh: bool = False
    once_key: str | None = None
    scroll_config: ScrollConfig | None = None

    def model_post_init(self, _context: object) -> None:
        if self.deferred_group is not None:
            self.deferred_group = _normalize_group(self.deferred_group)
            self.include_on_initial = False

        self.once_key = _normalize_once_key(self.once_key)
        if self.once_expires_at is not None:
            _resolve_once_expires_at(self.once_expires_at)

    def resolved_once_key(self, *, prop_name: str) -> str:
        return self.once_key or prop_name

    def resolved_once_expires_at(self) -> int | None:
        return _resolve_once_expires_at(self.once_expires_at)

    def with_once(self, *, key: str | None = None) -> Self:
        return self.model_copy(
            update={
                "once_enabled": True,
                "once_key": self.once_key if self.once_enabled else _normalize_once_key(key),
            },
        )


class Defer[T](Prop[T]):
    deferred_group: str = Field(default="default", alias="group")
    include_on_initial: bool = False


class OptionalProp[T](Prop[T]):
    include_on_initial: bool = False


class Always[T](Prop[T]):
    always_include: bool = True


class Once[T](Prop[T]):
    once_enabled: bool = True
    once_expires_at: RawExpiration | None = Field(default=None, alias="expires_at")
    once_fresh: bool = Field(default=False, alias="fresh")
    once_key: str | None = Field(default=None, alias="key")


class Merge[T](Prop[T]):
    deep: bool = False
    match_on: str | Sequence[str] | None = None
    mode: Literal["append", "prepend"] = "append"
    path: str = ""

    def model_post_init(self, _context: object) -> None:
        super().model_post_init(_context)
        if self.deep and self.mode == "prepend":
            msg = "Deep merge props cannot use prepend mode"
            raise ValueError(msg)

        self.merge_instructions = (
            MergeInstruction(
                match_on=_normalize_match_on(self.match_on),
                mode="deep" if self.deep else self.mode,
                path=_normalize_prop_path(self.path, allow_empty=True, name="merge path"),
            ),
        )


class Scroll[T](Prop[T]):
    current_page_path: str = "current_page"
    items_path: str = "data"
    next_page_path: str = "next_page"
    page_name: str = "page"
    previous_page_path: str = "previous_page"

    def model_post_init(self, _context: object) -> None:
        super().model_post_init(_context)
        if not (cleaned_page_name := self.page_name.strip()):
            msg = "The scroll page name must not be empty"
            raise ValueError(msg)

        self.scroll_config = ScrollConfig(
            current_page_path=_normalize_prop_path(
                self.current_page_path,
                allow_empty=True,
                name="scroll current page path",
            ),
            items_path=_normalize_prop_path(self.items_path, allow_empty=True, name="scroll items path"),
            next_page_path=_normalize_prop_path(self.next_page_path, allow_empty=True, name="scroll next page path"),
            page_name=cleaned_page_name,
            previous_page_path=_normalize_prop_path(
                self.previous_page_path,
                allow_empty=True,
                name="scroll previous page path",
            ),
        )


def _as_once_prop(value: object, *, key: str) -> Prop[Any]:
    if isinstance(value, Prop):
        return value.with_once(key=key)

    return Once(value=value, key=key)


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


__all__ = [
    "Always",
    "Defer",
    "Merge",
    "Once",
    "OptionalProp",
    "Prop",
    "PropSource",
    "Scroll",
    "SerializableProp",
]
