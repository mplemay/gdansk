from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from gdansk_bundler import Plugin
from gdansk_runtime import Runtime
from gdansk_runtime.script import Script

from gdansk_tailwindcss._core import TailwindCssTransformer


class _ShimInput(TypedDict):
    moduleId: str
    rootDir: str
    css: str
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
        self._transformer = TailwindCssTransformer(str(self._root))
        self._script = Script.from_file(str(_shim_path()), _ShimInput, _ShimOutput)
        self._runtime = Runtime(package_json=str(self._package_json))

    def transform(self, code: str, module_id: str, module_type: str) -> dict[str, str] | None:
        if module_type != "css":
            return None
        prepared = self._transformer.prepare(code, module_id)
        payload: _ShimInput = {
            "moduleId": module_id,
            "rootDir": str(self._root),
            "css": prepared.css,
            "candidates": prepared.candidates,
            "tailwindModuleUrl": prepared.tailwind_module_url,
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
