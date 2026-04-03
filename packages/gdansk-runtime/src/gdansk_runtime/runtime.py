# ruff: noqa: D100, D101, D102, D105, D107, SLF001

from __future__ import annotations

from os import PathLike, fspath
from pathlib import Path
from typing import TYPE_CHECKING, Self

from gdansk_runtime._core import (
    AsyncRuntimeContext as AsyncRuntimeContextImpl,
    Runtime as RuntimeImpl,
    RuntimeContext as RuntimeContextImpl,
)

__all__ = ["AsyncRuntimeContext", "Runtime", "RuntimeContext"]

_RUNTIME_CONTEXT_ALREADY_ACTIVE = "RuntimeContext is already active"

if TYPE_CHECKING:
    from gdansk_runtime.script import Script

    class RuntimeBase:
        def __new__(cls, *, package_json: str | None = None) -> Self: ...

    class RuntimeContextBase:
        def __new__(cls, contents: str) -> Self: ...
        def _ensure_inactive(self) -> None: ...
        def __enter__(self) -> Self: ...
        def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...

    class AsyncRuntimeContextBase:
        def __new__(cls, contents: str) -> Self: ...
        async def __aenter__(self) -> Self: ...
        async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...

    def _call_runtime_context_impl[I, O](context: RuntimeContext[I, O], value: object, /) -> object: ...

    async def _call_async_runtime_context_impl[I, O](
        context: AsyncRuntimeContext[I, O],
        value: object,
        /,
    ) -> object: ...
else:
    RuntimeBase = RuntimeImpl
    RuntimeContextBase = RuntimeContextImpl
    AsyncRuntimeContextBase = AsyncRuntimeContextImpl

    def _call_runtime_context_impl(context: RuntimeContextImpl, value: object, /) -> object:
        return RuntimeContextImpl.__call__(context, value)

    async def _call_async_runtime_context_impl(
        context: AsyncRuntimeContextImpl,
        value: object,
        /,
    ) -> object:
        return await AsyncRuntimeContextImpl.__call__(context, value)


def _normalize_runtime_path(path: str | PathLike[str] | None) -> str | None:
    if path is None:
        return None

    normalized_path = fspath(path)
    if not isinstance(normalized_path, str):
        msg = "Runtime.package_json must be a string path"
        raise TypeError(msg)

    if Path(normalized_path).is_absolute():
        return normalized_path

    return str(Path.cwd() / normalized_path)


class Runtime(RuntimeBase):
    def __new__(cls, *, package_json: str | PathLike[str] | None = None) -> Self:
        return super().__new__(cls, package_json=_normalize_runtime_path(package_json))

    def __call__[I, O](self, script: Script[I, O], /) -> RuntimeContext[I, O]:
        return RuntimeContext(script)


class RuntimeContext[I, O](RuntimeContextBase):
    def __new__(cls, script: Script[I, O], /) -> Self:
        return super().__new__(cls, script.contents)

    def __init__(self, script: Script[I, O], /) -> None:
        self._script: Script[I, O] = script
        self._async_context: AsyncRuntimeContext[I, O] | None = None

    def __enter__(self) -> Self:
        if self._async_context is not None:
            raise RuntimeError(_RUNTIME_CONTEXT_ALREADY_ACTIVE)

        super().__enter__()
        return self

    async def __aenter__(self) -> AsyncRuntimeContext[I, O]:
        if self._async_context is not None:
            raise RuntimeError(_RUNTIME_CONTEXT_ALREADY_ACTIVE)

        self._ensure_inactive()
        async_context = AsyncRuntimeContext(self._script)
        self._async_context = async_context

        try:
            return await async_context.__aenter__()
        except BaseException:
            self._async_context = None
            raise

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        async_context = self._async_context
        self._async_context = None
        if async_context is None:
            return

        await async_context.__aexit__(exc_type, exc_value, traceback)

    def __call__(self, value: I, /) -> O:
        result = _call_runtime_context_impl(self, self._script._serialize_input(value))
        return self._script._deserialize_output(result)


class AsyncRuntimeContext[I, O](AsyncRuntimeContextBase):
    def __new__(cls, script: Script[I, O], /) -> Self:
        return super().__new__(cls, script.contents)

    def __init__(self, script: Script[I, O], /) -> None:
        self._script: Script[I, O] = script

    async def __call__(self, value: I, /) -> O:
        result = await _call_async_runtime_context_impl(self, self._script._serialize_input(value))
        return self._script._deserialize_output(result)
