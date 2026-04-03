from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

import pytest
from pydantic import BaseModel

from gdansk_runtime import AsyncRuntimeContext, Runtime, Script

if TYPE_CHECKING:
    _TYPING_CONTENTS = "export default function(input) { return input; }"

    _typing_script = Script(contents=_TYPING_CONTENTS, inputs=int, outputs=str)

    async def _typing_async() -> None:
        async with Runtime()(_typing_script) as run:
            _typing_async_context: AsyncRuntimeContext[int, str] = run
            _typing_async_result: str = await run(1)


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
async def test_async_runtime_rejects_missing_default_export():
    script = Script(
        contents="export const value = 1;",
        inputs=int,
        outputs=int,
    )

    with pytest.raises(RuntimeError, match=r"default export.*missing"):
        async with Runtime()(script):
            pass


@pytest.mark.anyio
async def test_async_runtime_rejects_non_function_default_export():
    script = Script(
        contents="export default 1;",
        inputs=int,
        outputs=int,
    )

    with pytest.raises(RuntimeError, match=r"default export.*function"):
        async with Runtime()(script):
            pass


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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
        a, b = await asyncio.gather(run(1), run(2))

    # Worker serializes JS; gather does not order which call reaches the worker first.
    assert {a, b} == {(0, 1), (1, 3)} or {a, b} == {(0, 2), (2, 3)}
