from __future__ import annotations

import json
from dataclasses import dataclass, field
from os import PathLike, fspath
from typing import Any, Self

from gdansk_bundler import Plugin
from gdansk_runtime import Script
from gdansk_runtime._core import Script as ScriptImpl

from gdansk_vite._core import transform_assets_json

__all__ = ["VitePlugin", "ViteScript", "transform_css_assets"]


class ViteScript(Script[None, object]):
    def __new__(cls, contents: str) -> Self:
        return super().__new__(cls, contents, type(None), object)

    def __init__(self, contents: str) -> None:
        super().__init__(contents, type(None), object)

    @classmethod
    def from_file(cls, path: str | PathLike[str]) -> Self:
        source_path = cls._normalize_source_path(path)
        script = cls(cls._read_contents_from_path(source_path))
        object.__setattr__(script, "_source_path", source_path)
        return script

    @classmethod
    def from_script(cls, script: ScriptImpl) -> Self:
        vite_script = cls(script.contents)
        object.__setattr__(vite_script, "_source_path", script.source_path)
        return vite_script

    def __repr__(self) -> str:
        if self.source_path is not None:
            return f"ViteScript.from_file({self.source_path!r})"
        return "ViteScript(contents='<inline>')"


@dataclass(frozen=True, slots=True, kw_only=True)
class VitePlugin(Plugin):
    script: ScriptImpl = field(compare=False, hash=False, repr=False)
    _script_contents: str = field(init=False, repr=False)
    _script_source_path: str | None = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.script, ScriptImpl):
            msg = "VitePlugin.script must be a gdansk_runtime.Script or gdansk_vite.ViteScript"
            raise TypeError(msg)

        vite_script = self.script if isinstance(self.script, ViteScript) else ViteScript.from_script(self.script)
        Plugin.__init__(self, id="vite")
        object.__setattr__(self, "script", vite_script)
        object.__setattr__(self, "_script_contents", vite_script.contents)
        object.__setattr__(self, "_script_source_path", vite_script.source_path)

    def __repr__(self) -> str:
        return f"VitePlugin(script={self.script!r})"


def transform_css_assets(
    plugins: list[VitePlugin],
    *,
    root: str | PathLike[str],
    assets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    specs_payload = [
        {
            "code": plugin.script.contents,
            "sourcePath": plugin.script.source_path,
        }
        for plugin in plugins
    ]
    payload = json.loads(
        transform_assets_json(
            json.dumps(specs_payload),
            fspath(root),
            json.dumps(assets),
        ),
    )
    return payload["assets"], payload.get("watchFiles", [])
