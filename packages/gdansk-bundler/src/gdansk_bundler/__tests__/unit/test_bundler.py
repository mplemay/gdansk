from __future__ import annotations

import pytest

from gdansk_bundler import AsyncBundlerContext, Bundler, BundlerContext
from gdansk_bundler._core import AsyncBundlerContext as AsyncBundlerContextImpl, BundlerContext as BundlerContextImpl


def test_bundler_returns_python_bundler_context_subclass() -> None:
    context = Bundler(input="./index.ts")()

    assert type(context) is BundlerContext
    assert isinstance(context, BundlerContextImpl)


def test_bundler_context_returns_itself_from_enter() -> None:
    context = Bundler(input="./index.ts")()

    with context as run:
        assert run is context
        assert type(run) is BundlerContext


async def test_bundler_returns_python_async_bundler_context_subclass() -> None:
    context = Bundler(input="./index.ts")()

    async with context as run:
        assert type(run) is AsyncBundlerContext
        assert isinstance(run, AsyncBundlerContextImpl)


def test_bundler_rejects_plugins_in_first_milestone() -> None:
    with pytest.raises(NotImplementedError, match=r"Bundler\.plugins"):
        Bundler(input="./index.ts", plugins=[])


def test_bundler_rejects_watch_in_first_milestone() -> None:
    with pytest.raises(NotImplementedError, match=r"Bundler\.watch"):
        Bundler(input="./index.ts", watch={})
