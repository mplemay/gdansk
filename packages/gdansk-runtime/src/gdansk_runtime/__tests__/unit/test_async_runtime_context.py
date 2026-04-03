from __future__ import annotations

import pytest

from gdansk_runtime import AsyncRuntimeContext, Runtime, Script
from gdansk_runtime._core import AsyncRuntimeContext as AsyncRuntimeContextImpl


@pytest.mark.anyio
async def test_runtime_returns_python_async_runtime_context_subclass():
    script = Script(
        contents="export default async function(input) { return input + 1; }",
        inputs=int,
        outputs=int,
    )

    context = Runtime()(script)

    async with context as run:
        assert type(run) is AsyncRuntimeContext
        assert isinstance(run, AsyncRuntimeContextImpl)
        assert await run(1) == 2
