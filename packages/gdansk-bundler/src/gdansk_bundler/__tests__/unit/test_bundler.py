from __future__ import annotations

import pytest

from gdansk_bundler import AsyncBundlerContext, Bundler, BundlerContext


def test_bundler_returns_bundler_context() -> None:
    context = Bundler(input="./index.ts")()

    assert type(context) is BundlerContext


def test_bundler_context_returns_itself_from_enter() -> None:
    context = Bundler(input="./index.ts")()

    with context as run:
        assert run is context
        assert type(run) is BundlerContext


async def test_async_bundler_context_from_bundler() -> None:
    bundler = Bundler(input="./index.ts")

    async with AsyncBundlerContext(bundler) as run:
        assert type(run) is AsyncBundlerContext


def test_bundler_rejects_plugins_in_first_milestone() -> None:
    with pytest.raises(NotImplementedError, match=r"Bundler\.plugins"):
        Bundler(input="./index.ts", plugins=[])


def test_bundler_rejects_watch_in_first_milestone() -> None:
    with pytest.raises(NotImplementedError, match=r"Bundler\.watch"):
        Bundler(input="./index.ts", watch={})
