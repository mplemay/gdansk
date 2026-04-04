from __future__ import annotations

from os import PathLike

from pydantic import TypeAdapter

from gdansk_runtime import Script
from gdansk_runtime._core import Script as ScriptImpl


class _ScriptPath(PathLike[str]):
    def __init__(self, path: str) -> None:
        self._path = path

    def __fspath__(self) -> str:
        return self._path


def test_public_script_wraps_core_script():
    script = Script(
        contents="export default function(input) { return input + 1; }",
        inputs=int,
        outputs=int,
    )

    assert isinstance(script, ScriptImpl)
    assert isinstance(script.inputs, TypeAdapter)
    assert isinstance(script.outputs, TypeAdapter)


def test_script_from_file_uses_python_pathlike_support(tmp_path):
    script_path = tmp_path / "script.js"
    script_path.write_text("export default function(input) { return input + 1; }", encoding="utf-8")

    script = Script.from_file(_ScriptPath(str(script_path)), inputs=int, outputs=int)

    assert isinstance(script, ScriptImpl)
    assert script.contents == script_path.read_text(encoding="utf-8")
