from __future__ import annotations

from gdansk_bundler import Plugin

from gdansk_lightningcss._core import LightningCssTransformer, transform_css
from gdansk_lightningcss.bundle import CssBundleResult, bundle_css_paths, expand_css_imports, resolve_css_import_path


class LightningCssPlugin(Plugin):
    def __init__(self, *, minify: bool = True) -> None:
        super().__init__(name="lightningcss")
        self._transformer = LightningCssTransformer(minify=minify)

    def transform(self, code: str, module_id: str, module_type: str) -> dict[str, str] | None:
        if module_type != "css":
            return None
        out = self._transformer.transform(code, module_id)
        return {"code": out}


__all__ = [
    "CssBundleResult",
    "LightningCssPlugin",
    "LightningCssTransformer",
    "bundle_css_paths",
    "expand_css_imports",
    "resolve_css_import_path",
    "transform_css",
]
