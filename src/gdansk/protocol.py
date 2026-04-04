# ruff: noqa: D100

from __future__ import annotations

import os

from gdansk._core import LightningCSS, VitePlugin

type Plugin = LightningCSS | VitePlugin
type PathType = str | os.PathLike[str]

__all__ = ["PathType", "Plugin", "VitePlugin"]
