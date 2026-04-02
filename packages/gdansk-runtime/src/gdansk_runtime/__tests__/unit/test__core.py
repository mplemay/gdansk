from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Literal, cast

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from gdansk_runtime import Runtime, RuntimeContext, Script

if TYPE_CHECKING:
    _TYPING_CONTENTS = "export default function(input) { return input; }"

    _typing_script = Script(contents=_TYPING_CONTENTS, inputs=int, outputs=str)
    _typing_inputs: TypeAdapter[int] = _typing_script.inputs
    _typing_outputs: TypeAdapter[str] = _typing_script.outputs
    _typing_context: RuntimeContext[int, str] = Runtime()(_typing_script)

    _typing_literal_script = Script(
        contents=_TYPING_CONTENTS,
        inputs=TypeAdapter(Literal["ping"]),
        outputs=str,
    )
    _typing_literal_inputs: TypeAdapter[Literal["ping"]] = _typing_literal_script.inputs


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


def test_script_reuses_explicit_type_adapters():
    input_adapter = TypeAdapter(Literal["ping"])
    output_adapter = TypeAdapter(Literal["pong"])
    script = Script(
        contents="""
export default function() {
    return "pong";
}
""".strip(),
        inputs=input_adapter,
        outputs=output_adapter,
    )

    assert script.inputs is input_adapter
    assert script.outputs is output_adapter

    with Runtime()(script) as run:
        assert run("ping") == "pong"


def test_runtime_executes_inline_script_with_pydantic_io():
    class Output(BaseModel):
        value: int
        kind: str

    script = Script(
        contents="""
export default function(input) {
    return { value: input, kind: typeof input };
}
""".strip(),
        inputs=int,
        outputs=Output,
    )

    with Runtime()(script) as run:
        result = run(cast("Any", "2"))

    assert result == Output(value=2, kind="number")


def test_runtime_supports_models_and_iterable_output():
    class ScriptInput(BaseModel):
        a: int
        b: tuple[int, int]

    class ScriptOutput(BaseModel):
        total: int

    script = Script(
        contents="""
export default function(input) {
    return [{ total: input.a + input.b[0] + input.b[1] }];
}
""".strip(),
        inputs=ScriptInput,
        outputs=Iterable[ScriptOutput],
    )

    with Runtime()(script) as run:
        result = list(run(cast("Any", {"a": "1", "b": ["2", "3"]})))

    assert result == [ScriptOutput(total=6)]


def test_output_validation_runs_after_javascript_execution():
    script = Script(
        contents="""
let calls = 0;

export default function(input) {
    calls += 1;
    if (input) {
        return "bad";
    }
    return calls;
}
""".strip(),
        inputs=bool,
        outputs=int,
    )

    with Runtime()(script) as run:
        invalid_input = True
        with pytest.raises(ValidationError):
            run(invalid_input)

        valid_input = False
        assert run(valid_input) == 2


def test_runtime_context_shares_state_within_block():
    script = Script(
        contents="""
let counter = 0;

export default function(input) {
    counter += input;
    return counter;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        assert run(1) == 1
        assert run(2) == 3


def test_runtime_context_resets_state_across_blocks():
    script = Script(
        contents="""
let counter = 0;

export default function(input) {
    counter += input;
    return counter;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    runtime = Runtime()

    with runtime(script) as run:
        assert run(2) == 2

    with runtime(script) as run:
        assert run(2) == 2


def test_runtime_rejects_missing_default_export():
    script = Script(
        contents="export const value = 1;",
        inputs=int,
        outputs=int,
    )

    with pytest.raises(RuntimeError, match=r"default export.*missing"), Runtime()(script):
        pass


def test_runtime_rejects_non_function_default_export():
    script = Script(
        contents="export default 1;",
        inputs=int,
        outputs=int,
    )

    with pytest.raises(RuntimeError, match=r"default export.*function"), Runtime()(script):
        pass


def test_runtime_surfaces_javascript_errors():
    script = Script(
        contents="""
export default function() {
    throw new Error("boom");
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run, pytest.raises(RuntimeError, match="boom"):
        run(1)


def test_runtime_rejects_unsupported_javascript_values():
    script = Script(
        contents="""
export default function() {
    return undefined;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run, pytest.raises(ValueError, match="unsupported JavaScript value"):
        run(1)


def test_runtime_rejects_dependencies_for_now():
    with pytest.raises(NotImplementedError, match="dependencies"):
        Runtime(dependencies={"react": "18"})
