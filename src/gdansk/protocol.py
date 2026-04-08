from __future__ import annotations

import os

from gdansk_bundler import Plugin
from gdansk_vite import VitePlugin

type PathType = str | os.PathLike[str]

__all__ = ["PathType", "Plugin", "VitePlugin"]
