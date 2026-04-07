from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from gdansk_bundler import Plugin
from gdansk_runtime import Runtime
from gdansk_runtime.script import Script

from gdansk_tailwindcss._candidates import collect_candidates
from gdansk_tailwindcss._css_expand import expand_css_imports, importer_dir_for_module
from gdansk_tailwindcss._npm_package import resolve_tailwind_module_file


class _ShimInput(TypedDict):
    css: str
    moduleId: str
    rootDir: str
    candidates: list[str]
    tailwindModuleUrl: str


class _ShimOutput(TypedDict, total=False):
    code: str
    error: str


def _shim_path() -> Path:
    return Path(__file__).resolve().parent / "tailwind_shim.mjs"


class TailwindCssPlugin(Plugin):
    def __init__(self, *, package_json: str | Path) -> None:
        super().__init__(name="tailwindcss")
        self._package_json = Path(package_json).resolve()
        self._root = self._package_json.parent.resolve()
        self._script = Script.from_file(str(_shim_path()), _ShimInput, _ShimOutput)
        self._runtime = Runtime(package_json=str(self._package_json))

    def transform(self, code: str, module_id: str, module_type: str) -> dict[str, str] | None:
        if module_type != "css":
            return None
        importer_dir = importer_dir_for_module(module_id, self._root)
        expanded = expand_css_imports(code, importer_dir, self._root)
        tailwind_path = resolve_tailwind_module_file(self._root)
        payload: _ShimInput = {
            "css": expanded,
            "moduleId": module_id,
            "rootDir": str(self._root),
            "candidates": collect_candidates(self._root),
            "tailwindModuleUrl": tailwind_path.as_uri(),
        }
        with self._runtime(self._script) as ctx:
            out = ctx(payload)
        if err := out.get("error"):
            msg = err if isinstance(err, str) else str(err)
            raise RuntimeError(msg)
        co = out.get("code")
        if co is None:
            return None
        return {"code": co}


__all__ = ["TailwindCssPlugin"]
