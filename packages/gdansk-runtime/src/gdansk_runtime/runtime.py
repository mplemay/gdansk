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
        def __new__(cls, contents: str, entry_path: str, root_path: str) -> Self: ...
        def _ensure_inactive(self) -> None: ...
        def __enter__(self) -> Self: ...
        def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...

    class AsyncRuntimeContextBase:
        def __new__(cls, contents: str, entry_path: str, root_path: str) -> Self: ...
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


class Runtime(RuntimeBase):
    @staticmethod
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

    def __new__(cls, *, package_json: str | PathLike[str] | None = None) -> Self:
        return super().__new__(cls, package_json=cls._normalize_runtime_path(package_json))

    def __init__(self, *, package_json: str | PathLike[str] | None = None) -> None:
        normalized_path = self._normalize_runtime_path(package_json)
        self._package_json_path = Path(normalized_path) if normalized_path is not None else None

    def _execution_paths[I, O](self, script: Script[I, O], /) -> tuple[str, str]:
        if script._source_path is not None:
            entry_path = Path(script._source_path)
            root_path = self._package_json_path.parent if self._package_json_path is not None else entry_path.parent
            return str(entry_path), str(root_path)

        root_path = self._package_json_path.parent if self._package_json_path is not None else Path.cwd()
        return str(root_path / "__gdansk_runtime_inline__.js"), str(root_path)

    def __call__[I, O](self, script: Script[I, O], /) -> RuntimeContext[I, O]:
        entry_path, root_path = self._execution_paths(script)
        return RuntimeContext(script, entry_path=entry_path, root_path=root_path)


class RuntimeContext[I, O](RuntimeContextBase):
    def __new__(
        cls,
        script: Script[I, O],
        /,
        *,
        entry_path: str | None = None,
        root_path: str | None = None,
    ) -> Self:
        resolved_entry_path = entry_path or script._source_path or str(Path.cwd() / "__gdansk_runtime_inline__.js")
        resolved_root_path = root_path or str(Path(resolved_entry_path).parent)
        return super().__new__(cls, script.contents, resolved_entry_path, resolved_root_path)

    def __init__(
        self,
        script: Script[I, O],
        /,
        *,
        entry_path: str | None = None,
        root_path: str | None = None,
    ) -> None:
        self._script: Script[I, O] = script
        self._async_context: AsyncRuntimeContext[I, O] | None = None
        self._entry_path = entry_path or script._source_path or str(Path.cwd() / "__gdansk_runtime_inline__.js")
        self._root_path = root_path or str(Path(self._entry_path).parent)

    def __enter__(self) -> Self:
        if self._async_context is not None:
            raise RuntimeError(_RUNTIME_CONTEXT_ALREADY_ACTIVE)

        super().__enter__()
        return self

    async def __aenter__(self) -> AsyncRuntimeContext[I, O]:
        if self._async_context is not None:
            raise RuntimeError(_RUNTIME_CONTEXT_ALREADY_ACTIVE)

        self._ensure_inactive()
        async_context = AsyncRuntimeContext(
            self._script,
            entry_path=self._entry_path,
            root_path=self._root_path,
        )
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
    def __new__(
        cls,
        script: Script[I, O],
        /,
        *,
        entry_path: str | None = None,
        root_path: str | None = None,
    ) -> Self:
        resolved_entry_path = entry_path or script._source_path or str(Path.cwd() / "__gdansk_runtime_inline__.js")
        resolved_root_path = root_path or str(Path(resolved_entry_path).parent)
        return super().__new__(cls, script.contents, resolved_entry_path, resolved_root_path)

    def __init__(
        self,
        script: Script[I, O],
        /,
        *,
        entry_path: str | None = None,
        root_path: str | None = None,
    ) -> None:
        self._script: Script[I, O] = script
        self._entry_path = entry_path or script._source_path or str(Path.cwd() / "__gdansk_runtime_inline__.js")
        self._root_path = root_path or str(Path(self._entry_path).parent)

    async def __call__(self, value: I, /) -> O:
        result = await _call_async_runtime_context_impl(self, self._script._serialize_input(value))
        return self._script._deserialize_output(result)
