from __future__ import annotations

import json
from dataclasses import dataclass, field
from os import PathLike, fspath
from pathlib import Path
from typing import Any

from gdansk_bundler import Plugin

from gdansk_vite._core import transform_assets_json

__all__ = ["VitePlugin", "transform_css_assets"]


def _normalize_runtime_specifier(specifier: str | PathLike[str], *, root: Path) -> str:
    specifier = fspath(specifier)
    if specifier.startswith(("./", "../")):
        return str((root / specifier).resolve())
    if Path(specifier).is_absolute():
        return str(Path(specifier).resolve())
    candidate = root / specifier
    if candidate.exists():
        return str(candidate.resolve())
    return specifier


@dataclass(frozen=True, slots=True, kw_only=True)
class VitePlugin(Plugin):
    specifier: str | PathLike[str]
    options: object = field(default_factory=dict)

    def __post_init__(self) -> None:
        specifier = fspath(self.specifier)
        if not isinstance(specifier, str) or not specifier.strip():
            msg = "VitePlugin.specifier must be a non-empty string or path"
            raise ValueError(msg)
        normalized = specifier.replace("\\", "/")
        try:
            json.dumps(self.options)
        except TypeError as err:
            msg = "VitePlugin.options must be JSON serializable"
            raise TypeError(msg) from err
        Plugin.__init__(self, id="vite")
        object.__setattr__(self, "specifier", normalized)


def transform_css_assets(
    plugins: list[VitePlugin],
    *,
    root: str | PathLike[str],
    assets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    root_path = Path(root).resolve()
    specs_payload = [
        {
            "specifier": _normalize_runtime_specifier(plugin.specifier, root=root_path),
            "options": plugin.options,
        }
        for plugin in plugins
    ]
    payload = json.loads(
        transform_assets_json(
            json.dumps(specs_payload),
            str(root_path),
            json.dumps(assets),
        ),
    )
    return payload["assets"], payload.get("watchFiles", [])
