from __future__ import annotations

import re

import pytest

from gdansk_bundler import AsyncBundlerContext, Bundler, BundlerContext, Plugin


def test_bundler_returns_bundler_context() -> None:
    context = Bundler()()

    assert type(context) is BundlerContext


def test_bundler_context_returns_itself_from_enter() -> None:
    context = Bundler()()

    with context as run:
        assert run is context
        assert type(run) is BundlerContext


async def test_async_bundler_context_from_bundler() -> None:
    bundler = Bundler()

    async with AsyncBundlerContext(bundler) as run:
        assert type(run) is AsyncBundlerContext


def test_bundler_accepts_empty_plugins_list() -> None:
    b = Bundler(plugins=[])
    assert b is not None


def test_bundler_accepts_plugins_as_tuple() -> None:
    class IdlePlugin(Plugin):
        def __init__(self) -> None:
            super().__init__(id="idle")

    b = Bundler(plugins=(IdlePlugin(),))
    assert b is not None


def test_bundler_rejects_dict_plugin() -> None:
    with pytest.raises(TypeError, match="Plugin"):
        Bundler(plugins=[{"name": "legacy"}])  # ty: ignore[invalid-argument-type]


def test_bundler_rejects_watch_in_first_milestone() -> None:
    bundler = Bundler()
    with pytest.raises(NotImplementedError, match=r"Bundler\.watch"):
        bundler(watch={})


def test_bundler_rejects_unknown_resolve_key() -> None:
    with pytest.raises(NotImplementedError, match=r"Bundler\.resolve\.not_a_real_key"):
        Bundler(resolve={"not_a_real_key": True})


def test_bundler_accepts_platform_and_treeshake_bool() -> None:
    b = Bundler(platform="node", treeshake=False)
    assert b is not None


def test_bundler_accepts_external_strings_and_regex() -> None:
    b = Bundler(
        external=["fs", re.compile(r"^node:")],
    )
    assert b is not None


def test_bundler_rejects_unknown_output_key() -> None:
    with pytest.raises(NotImplementedError, match=r"Bundler\.output\.nope"):
        Bundler(output={"nope": True})
