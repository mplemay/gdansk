from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Literal, cast

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from gdansk_runtime import AsyncRuntimeContext, Runtime, RuntimeContext, Script

if TYPE_CHECKING:
    from pathlib import Path

    _TYPING_CONTENTS = "export default function(input) { return input; }"

    _typing_runtime = Runtime(package_json="package.json")
    _typing_script = Script(contents=_TYPING_CONTENTS, inputs=int, outputs=str)
    _typing_inputs: TypeAdapter[int] = _typing_script.inputs
    _typing_outputs: TypeAdapter[str] = _typing_script.outputs
    _typing_context: RuntimeContext[int, str] = Runtime()(_typing_script)
    _typing_file_script: Script[int, str] = Script.from_file("script.js", inputs=int, outputs=str)

    _typing_literal_script = Script(
        contents=_TYPING_CONTENTS,
        inputs=TypeAdapter(Literal["ping"]),
        outputs=str,
    )
    _typing_literal_inputs: TypeAdapter[Literal["ping"]] = _typing_literal_script.inputs

    async def _typing_async() -> None:
        async with Runtime()(_typing_script) as run:
            _typing_async_context: AsyncRuntimeContext[int, str] = run
            _typing_async_result: str = await run(1)


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


def test_runtime_accepts_package_json_paths(tmp_path: Path):
    package_json = tmp_path / "package.json"

    assert isinstance(Runtime(package_json=package_json), Runtime)
    assert isinstance(Runtime(package_json=str(package_json)), Runtime)


def test_runtime_context_rejects_calls_before_enter():
    script = Script(
        contents="""
export default function(input) {
    return input + 1;
}
""".strip(),
        inputs=int,
        outputs=int,
    )
    context = Runtime()(script)

    with pytest.raises(RuntimeError, match="not active"):
        context(1)


def test_runtime_context_rejects_reentry_while_active():
    script = Script(
        contents="""
export default function(input) {
    return input + 1;
}
""".strip(),
        inputs=int,
        outputs=int,
    )
    context = Runtime()(script)

    with context, pytest.raises(RuntimeError, match="already active"):
        context.__enter__()


def test_runtime_context_can_be_reused_after_exit():
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
    context = Runtime()(script)

    with context:
        assert context(2) == 2

    with context:
        assert context(2) == 2


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


def test_runtime_does_not_run_javascript_when_input_validation_fails():
    script = Script(
        contents="""
let calls = 0;

export default function(input) {
    calls += 1;
    return calls + input;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        with pytest.raises(ValidationError):
            run("bad")

        assert run(1) == 2


def test_runtime_does_not_run_javascript_when_input_cannot_serialize():
    script = Script(
        contents="""
let calls = 0;

export default function(input) {
    calls += 1;
    return calls + input;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        with pytest.raises(TypeError, match="JSON-compatible"):
            run(10**100)

        assert run(1) == 2


def test_runtime_supports_async_default_export():
    script = Script(
        contents="""
export default async function(input) {
    return await Promise.resolve(input + 1);
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        assert run(1) == 2


def test_runtime_honors_top_level_await_before_calls():
    script = Script(
        contents="""
const offset = await Promise.resolve(41);

export default function(input) {
    return offset + input;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        assert run(1) == 42


def test_runtime_exposes_web_api_globals():
    script = Script(
        contents="""
export default function() {
    const bytes = new TextEncoder().encode("hello");
    const text = new TextDecoder().decode(bytes);
    const location = new URL("/runtime?value=1", "https://example.com/base");
    const channel = new MessageChannel();
    const blob = new Blob(["hello"]);
    return {
        text,
        href: location.href,
        search: location.searchParams.get("value"),
        hasMessagePort:
            typeof channel.port1.postMessage === "function" &&
            typeof channel.port2.postMessage === "function",
        blobSize: blob.size,
        streamTypes: [
            typeof ReadableStream === "function",
            typeof WritableStream === "function",
            typeof TransformStream === "function",
        ],
    };
}
""".strip(),
        inputs=int,
        outputs=dict[str, object],
    )

    with Runtime()(script) as run:
        result = run(0)

    assert result == {
        "text": "hello",
        "href": "https://example.com/runtime?value=1",
        "search": "1",
        "hasMessagePort": True,
        "blobSize": 5,
        "streamTypes": [True, True, True],
    }


def test_runtime_bootstraps_web_globals_before_module_evaluation():
    script = Script(
        contents="""
const encoded = new TextEncoder().encode("ok");
const channel = new MessageChannel();
const bootstrapped =
    encoded.length === 2 &&
    typeof channel.port1.postMessage === "function";

export default function() {
    return bootstrapped;
}
""".strip(),
        inputs=int,
        outputs=bool,
    )

    with Runtime()(script) as run:
        assert run(0) is True


def test_runtime_supports_timers():
    script = Script(
        contents="""
export default async function(input) {
    return await new Promise((resolve) => {
        setTimeout(() => resolve(input + 1), 0);
    });
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        assert run(1) == 2


def test_runtime_recovers_after_javascript_error_within_context():
    script = Script(
        contents="""
let calls = 0;

export default function(input) {
    if (input < 0) {
        throw new Error("boom");
    }
    calls += input;
    return calls;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        with pytest.raises(RuntimeError, match="boom"):
            run(-1)

        assert run(2) == 2


def test_runtime_recovers_after_deserialize_error_within_context():
    script = Script(
        contents="""
let calls = 0;

export default function(input) {
    if (input < 0) {
        return undefined;
    }
    calls += input;
    return calls;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    with Runtime()(script) as run:
        with pytest.raises(ValueError, match="unsupported JavaScript value"):
            run(-1)

        assert run(2) == 2


def test_runtime_lock_requires_package_json():
    with pytest.raises(RuntimeError, match="package_json"):
        Runtime().lock()


def test_runtime_sync_requires_package_json():
    with pytest.raises(RuntimeError, match="package_json"):
        Runtime().sync()


@pytest.mark.asyncio
async def test_async_runtime_executes_inline_script_with_pydantic_io():
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

    async with Runtime()(script) as run:
        result = await run(cast("Any", "2"))

    assert result == Output(value=2, kind="number")


@pytest.mark.asyncio
async def test_runtime_alock_requires_package_json():
    with pytest.raises(RuntimeError, match="package_json"):
        await Runtime().alock()


@pytest.mark.asyncio
async def test_async_runtime_context_shares_state_within_block():
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

    async with Runtime()(script) as run:
        assert await run(1) == 1
        assert await run(2) == 3


@pytest.mark.asyncio
async def test_async_runtime_context_resets_state_across_blocks():
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

    async with runtime(script) as run:
        assert await run(2) == 2

    async with runtime(script) as run:
        assert await run(2) == 2


@pytest.mark.asyncio
async def test_async_runtime_context_rejects_calls_after_exit():
    script = Script(
        contents="""
export default function(input) {
    return input + 1;
}
""".strip(),
        inputs=int,
        outputs=int,
    )
    run: AsyncRuntimeContext[int, int] | None = None

    async with Runtime()(script) as handle:
        run = handle
        assert await handle(1) == 2

    assert run is not None

    with pytest.raises(RuntimeError, match="not active"):
        await run(1)


@pytest.mark.asyncio
async def test_async_runtime_context_rejects_reentry_while_active():
    script = Script(
        contents="""
export default function(input) {
    return input + 1;
}
""".strip(),
        inputs=int,
        outputs=int,
    )
    context = Runtime()(script)

    async with context:
        with pytest.raises(RuntimeError, match="already active"):
            await context.__aenter__()


@pytest.mark.asyncio
async def test_async_runtime_context_can_be_reused_after_exit():
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
    context = Runtime()(script)

    async with context as run:
        assert await run(2) == 2

    async with context as run:
        assert await run(2) == 2


@pytest.mark.asyncio
async def test_async_runtime_rejects_missing_default_export():
    script = Script(
        contents="export const value = 1;",
        inputs=int,
        outputs=int,
    )

    with pytest.raises(RuntimeError, match=r"default export.*missing"):
        async with Runtime()(script):
            pass


@pytest.mark.asyncio
async def test_async_runtime_rejects_non_function_default_export():
    script = Script(
        contents="export default 1;",
        inputs=int,
        outputs=int,
    )

    with pytest.raises(RuntimeError, match=r"default export.*function"):
        async with Runtime()(script):
            pass


@pytest.mark.asyncio
async def test_async_runtime_supports_async_default_export():
    script = Script(
        contents="""
export default async function(input) {
    return await Promise.resolve(input + 1);
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    async with Runtime()(script) as run:
        assert await run(1) == 2


@pytest.mark.asyncio
async def test_async_runtime_honors_top_level_await_before_calls():
    script = Script(
        contents="""
const offset = await Promise.resolve(41);

export default function(input) {
    return offset + input;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    async with Runtime()(script) as run:
        assert await run(1) == 42


@pytest.mark.asyncio
async def test_async_runtime_surfaces_javascript_errors():
    script = Script(
        contents="""
export default function() {
    throw new Error("boom");
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    async with Runtime()(script) as run:
        with pytest.raises(RuntimeError, match="boom"):
            await run(1)


@pytest.mark.asyncio
async def test_async_runtime_rejects_unsupported_javascript_values():
    script = Script(
        contents="""
export default function() {
    return undefined;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    async with Runtime()(script) as run:
        with pytest.raises(ValueError, match="unsupported JavaScript value"):
            await run(1)


@pytest.mark.asyncio
async def test_async_runtime_recovers_after_javascript_error_within_context():
    script = Script(
        contents="""
let calls = 0;

export default function(input) {
    if (input < 0) {
        throw new Error("boom");
    }
    calls += input;
    return calls;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    async with Runtime()(script) as run:
        with pytest.raises(RuntimeError, match="boom"):
            await run(-1)

        assert await run(2) == 2


@pytest.mark.asyncio
async def test_async_runtime_recovers_after_deserialize_error_within_context():
    script = Script(
        contents="""
let calls = 0;

export default function(input) {
    if (input < 0) {
        return undefined;
    }
    calls += input;
    return calls;
}
""".strip(),
        inputs=int,
        outputs=int,
    )

    async with Runtime()(script) as run:
        with pytest.raises(ValueError, match="unsupported JavaScript value"):
            await run(-1)

        assert await run(2) == 2


@pytest.mark.asyncio
async def test_async_runtime_serializes_concurrent_calls():
    script = Script(
        contents="""
let counter = 0;

export default async function(input) {
    const before = counter;
    await Promise.resolve();
    counter = before + input;
    return [before, counter];
}
""".strip(),
        inputs=int,
        outputs=tuple[int, int],
    )

    async with Runtime()(script) as run:
        first, second = await asyncio.gather(run(1), run(2))

    assert first == (0, 1)
    assert second == (1, 3)
