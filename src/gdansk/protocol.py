# ruff: noqa: D100, D101

from __future__ import annotations

from typing import Protocol

from gdansk._core import VitePlugin


class BundlerPlugin(Protocol):
    id: str


__all__ = ["BundlerPlugin", "VitePlugin"]
