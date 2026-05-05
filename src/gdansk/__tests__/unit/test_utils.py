from __future__ import annotations

from gdansk.utils import maybe_awaitable


async def test_maybe_awaitable_wraps_sync_callbacks():
    def callback(value: int) -> str:
        return f"value-{value}"

    wrapped = maybe_awaitable(callback)

    assert await wrapped(1) == "value-1"


async def test_maybe_awaitable_wraps_async_callbacks():
    async def callback(value: int) -> str:
        return f"value-{value}"

    wrapped = maybe_awaitable(callback)

    assert await wrapped(2) == "value-2"
