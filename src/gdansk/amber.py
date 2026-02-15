from __future__ import annotations

import asyncio
import inspect
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gdansk._core import bundle

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcp.server.fastmcp import FastMCP

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light dark">
</head>
<body>
<div id="root"></div>
<script type="module">
{js}
</script>
</body>
</html>"""


def _slugify(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


class Amber:
    def __init__(self, mcp: FastMCP, *, dev: bool = False, output: Path = Path(".gdansk")) -> None:
        self._mcp = mcp
        self._dev = dev
        self._output = output
        self._ui_paths: set[Path] = set()
        self._bundle_future: asyncio.Future[None] | None = None

    def _ensure_bundling(self) -> None:
        if self._bundle_future is None and self._ui_paths:
            self._bundle_future = asyncio.ensure_future(bundle(self._ui_paths, dev=self._dev, output=self._output))

    def tool(self, *, ui: Path | None = None, **kwargs: Any) -> Callable:
        if ui is None:
            return self._mcp.tool(**kwargs)

        # Resolve ui path relative to the caller's file, then make cwd-relative
        if not ui.is_absolute():
            caller_dir = Path(inspect.stack()[1].filename).parent.resolve()
            ui = (caller_dir / ui).resolve().relative_to(Path.cwd().resolve())

        self._ui_paths.add(ui)
        js_path = self._output / ui.with_suffix(".js")
        resource_uri = f"ui://{_slugify(self._mcp.name)}/{ui.stem}"

        meta = kwargs.pop("meta", None) or {}
        meta["ui"] = {"resourceUri": resource_uri}

        def decorator(fn: Callable) -> Callable:
            self._mcp.tool(meta=meta, **kwargs)(fn)

            @self._mcp.resource(resource_uri, mime_type="text/html;profile=mcp-app")
            async def _resource_handler() -> str:
                self._ensure_bundling()
                while not js_path.exists():
                    await asyncio.sleep(0.05)
                js = js_path.read_text(encoding="utf-8")
                return _HTML_TEMPLATE.format(js=js)

            return fn

        return decorator
