# ruff: noqa: D100

from __future__ import annotations

import os
from typing import TypeAlias

from gdansk._core import LightningCSS, VitePlugin

Plugin: TypeAlias = LightningCSS | VitePlugin
PathType: TypeAlias = str | os.PathLike[str]

__all__ = ["PathType", "Plugin", "VitePlugin"]
