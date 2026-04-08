from __future__ import annotations

import os

from gdansk_bundler import Plugin as BundlerPlugin
from gdansk_vite import VitePlugin

type Plugin = BundlerPlugin | VitePlugin
type PathType = str | os.PathLike[str]

__all__ = ["PathType", "Plugin", "VitePlugin"]
