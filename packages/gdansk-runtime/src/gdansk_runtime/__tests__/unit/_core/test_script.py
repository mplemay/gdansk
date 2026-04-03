from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pytest
from pydantic import TypeAdapter, ValidationError

from gdansk_runtime import Runtime, Script

if TYPE_CHECKING:
    from pathlib import Path
    from typing import assert_type

    _TYPING_CONTENTS = "export default function(input) { return input; }"

    _typing_script = Script(contents=_TYPING_CONTENTS, inputs=int, outputs=str)
    _typing_inputs: TypeAdapter[int] = _typing_script.inputs
    _typing_outputs: TypeAdapter[str] = _typing_script.outputs
    _typing_file_script: Script[int, str] = Script.from_file("script.js", inputs=int, outputs=str)
    assert_type(_typing_script, Script[int, str])
    assert_type(_typing_inputs, TypeAdapter[int])
    assert_type(_typing_outputs, TypeAdapter[str])
    assert_type(_typing_file_script, Script[int, str])


def test_script_accepts_non_model_annotations():
    script = Script(
        contents="""
export default function(input) {
    return [input[1], input[0]];
}
""".strip(),
        inputs=tuple[int, str],
        outputs=tuple[str, int],
    )

    with Runtime()(script) as run:
        result = run((1, "two"))

    assert result == ("two", 1)


def test_script_normalizes_annotations_to_type_adapters():
    script = Script(
        contents="""
export default function(input) {
    return input;
}
""".strip(),
        inputs=int,
        outputs=tuple[str, int],
    )

    assert isinstance(script.inputs, TypeAdapter)
    assert isinstance(script.outputs, TypeAdapter)
    assert script.inputs.validate_python("1") == 1
    assert script.outputs.validate_python(["two", 2]) == ("two", 2)


def test_script_accepts_literal_annotations():
    script = Script(
        contents="""
export default function() {
    return "pong";
}
""".strip(),
        inputs=Literal["ping"],
        outputs=Literal["pong"],
    )

    assert isinstance(script.inputs, TypeAdapter)
    assert isinstance(script.outputs, TypeAdapter)
    assert script.inputs.validate_python("ping") == "ping"
    assert script.outputs.validate_python("pong") == "pong"

    with pytest.raises(ValidationError):
        script.inputs.validate_python("pong")

    with Runtime()(script) as run:
        assert run("ping") == "pong"


@pytest.mark.parametrize("contents", ["", " \n\t "])
def test_script_rejects_blank_contents(contents):
    with pytest.raises(ValueError, match="must not be empty"):
        Script(contents=contents, inputs=int, outputs=int)


def test_script_from_file_loads_contents_and_executes(tmp_path: Path):
    script_path = tmp_path / "script.js"
    script_path.write_text(
        """
export default function(input) {
    return input + 1;
}
""".strip(),
        encoding="utf-8",
    )

    script = Script.from_file(script_path, inputs=int, outputs=int)

    assert script.contents == script_path.read_text(encoding="utf-8")

    with Runtime()(script) as run:
        assert run(1) == 2


def test_script_from_file_accepts_string_paths(tmp_path: Path):
    script_path = tmp_path / "script.js"
    script_path.write_text("export default function(input) { return input; }", encoding="utf-8")

    script = Script.from_file(str(script_path), inputs=int, outputs=int)

    assert script.contents == "export default function(input) { return input; }"


def test_script_from_file_rejects_blank_file(tmp_path: Path):
    script_path = tmp_path / "script.js"
    script_path.write_text(" \n\t ", encoding="utf-8")

    with pytest.raises(ValueError, match="must not be empty"):
        Script.from_file(script_path, inputs=int, outputs=int)


def test_script_from_file_raises_for_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        Script.from_file(tmp_path / "missing.js", inputs=int, outputs=int)


def test_script_from_file_surfaces_decode_errors(tmp_path: Path):
    script_path = tmp_path / "script.js"
    script_path.write_bytes(b"\xff")

    with pytest.raises(OSError, match="UTF-8"):
        Script.from_file(script_path, inputs=int, outputs=int)
