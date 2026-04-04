from __future__ import annotations

from gdansk_runtime import Runtime, RuntimeContext, Script
from gdansk_runtime._core import RuntimeContext as RuntimeContextImpl


def test_runtime_returns_python_runtime_context_subclass():
    script = Script(
        contents="export default function(input) { return input + 1; }",
        inputs=int,
        outputs=int,
    )

    context = Runtime()(script)

    assert type(context) is RuntimeContext
    assert isinstance(context, RuntimeContextImpl)


def test_runtime_context_serializes_with_python_script_wrapper():
    script = Script(
        contents="""
export default function(input) {
    return [input[1], input[0]];
}
""".strip(),
        inputs=tuple[int, str],
        outputs=tuple[str, int],
    )

    context = Runtime()(script)

    with context as run:
        assert run is context
        assert type(run) is RuntimeContext
        assert run((1, "two")) == ("two", 1)
