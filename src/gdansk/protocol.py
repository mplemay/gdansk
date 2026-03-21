# ruff: noqa: D100

from __future__ import annotations

from typing import TypeAlias

from gdansk._core import LightningCSS, VitePlugin

Plugin: TypeAlias = LightningCSS | VitePlugin

__all__ = ["Plugin", "VitePlugin"]
