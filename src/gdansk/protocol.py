# ruff: noqa: D100,D101,D105

from __future__ import annotations

import json
from dataclasses import dataclass, field
from os import PathLike, fspath
from typing import Any, Protocol


class BundlerPlugin(Protocol):
    id: str


@dataclass(slots=True, kw_only=True, frozen=True)
class VitePlugin:
    specifier: str | PathLike[str]
    options: Any = field(default_factory=dict)

    def __post_init__(self) -> None:
        specifier = fspath(self.specifier)
        if not isinstance(specifier, str) or not specifier.strip():
            msg = "VitePlugin.specifier must be a non-empty string or path"
            raise ValueError(msg)
        object.__setattr__(self, "specifier", specifier)

        try:
            json.dumps(self.options)
        except TypeError as exc:
            msg = "VitePlugin.options must be JSON serializable"
            raise TypeError(msg) from exc
