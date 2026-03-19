# ruff: noqa: D100,D101,D102,D105

from __future__ import annotations

import json
from dataclasses import dataclass, field
from os import PathLike, fspath
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import asyncio
    from pathlib import Path


class BundlerPlugin(Protocol):
    id: str


class LifecyclePlugin(Protocol):
    async def build(self, *, pages: Path, output: Path) -> None: ...

    async def watch(self, *, pages: Path, output: Path, stop_event: asyncio.Event) -> None: ...


Plugin = LifecyclePlugin


@dataclass(slots=True, kw_only=True, frozen=True)
class JsPluginSpec:
    specifier: str | PathLike[str]
    options: Any = field(default_factory=dict)

    def __post_init__(self) -> None:
        specifier = fspath(self.specifier)
        if not isinstance(specifier, str) or not specifier.strip():
            msg = "JsPluginSpec.specifier must be a non-empty string or path"
            raise ValueError(msg)
        object.__setattr__(self, "specifier", specifier)

        try:
            json.dumps(self.options)
        except TypeError as exc:
            msg = "JsPluginSpec.options must be JSON serializable"
            raise TypeError(msg) from exc
