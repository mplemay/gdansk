# ruff: noqa: D100, D101, D102, D105, D107, PLR0913, SLF001

from __future__ import annotations

from collections.abc import Mapping, Sequence
from os import PathLike, fspath
from pathlib import Path
from typing import TYPE_CHECKING, Self

from gdansk_bundler._core import (
    AsyncBundlerContext as AsyncBundlerContextImpl,
    Bundler as BundlerImpl,
    BundlerContext as BundlerContextImpl,
    BundlerOutput as BundlerOutputImpl,
)
from gdansk_bundler.models import BundlerOutput

__all__ = ["AsyncBundlerContext", "Bundler", "BundlerContext"]

_BUNDLER_CONTEXT_ALREADY_ACTIVE = "BundlerContext is already active"

type InputPath = str | PathLike[str]
type InputOption = InputPath | Sequence[InputPath] | Mapping[str, InputPath]
type ResolveOption = Mapping[str, object]
type DevtoolsOption = bool | Mapping[str, object]
type OutputOption = Mapping[str, object]


if TYPE_CHECKING:

    def _call_bundler_context_impl(
        context: BundlerContext,
        output: dict[str, object] | None = None,
        /,
        *,
        write: bool | None = None,
    ) -> BundlerOutputImpl: ...

    async def _call_async_bundler_context_impl(
        context: AsyncBundlerContext,
        output: dict[str, object] | None = None,
        /,
        *,
        write: bool | None = None,
    ) -> BundlerOutputImpl: ...
else:

    def _call_bundler_context_impl(
        context: BundlerContextImpl,
        output: object | None = None,
        /,
        *,
        write: bool | None = None,
    ) -> BundlerOutputImpl:
        return BundlerContextImpl.__call__(context, output, write=write)

    async def _call_async_bundler_context_impl(
        context: AsyncBundlerContextImpl,
        output: object | None = None,
        /,
        *,
        write: bool | None = None,
    ) -> BundlerOutputImpl:
        return await AsyncBundlerContextImpl.__call__(context, output, write=write)


def _normalize_string_path(value: str | PathLike[str], /, *, label: str, absolute: bool = False) -> str:
    normalized = fspath(value)
    if not isinstance(normalized, str):
        msg = f"{label} must be a string path"
        raise TypeError(msg)

    if absolute and not Path(normalized).is_absolute():
        return str(Path.cwd() / normalized)

    return normalized


def _normalize_string_key_mapping(
    mapping: Mapping[object, object],
    /,
    *,
    label: str,
) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in mapping.items():
        if not isinstance(key, str):
            msg = f"{label} keys must be strings"
            raise TypeError(msg)
        normalized[key] = value
    return normalized


def _normalize_input(value: InputOption, /) -> str | list[str] | dict[str, str]:
    if isinstance(value, (str, PathLike)):
        return _normalize_string_path(value, label="Bundler.input")

    if isinstance(value, Mapping):
        normalized: dict[str, str] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                msg = "Bundler.input mapping keys must be strings"
                raise TypeError(msg)
            normalized[key] = _normalize_string_path(
                item,
                label=f"Bundler.input[{key!r}]",
            )
        return normalized

    if isinstance(value, Sequence):
        return [_normalize_string_path(item, label="Bundler.input") for item in value]

    msg = "Bundler.input must be a string path, a sequence of string paths, or a mapping of entry names to paths"
    raise TypeError(msg)


def _normalize_string_sequence(value: object, /, *, label: str) -> list[str]:
    if isinstance(value, str):
        msg = f"{label} must be a sequence of strings"
        raise TypeError(msg)

    if not isinstance(value, Sequence):
        msg = f"{label} must be a sequence of strings"
        raise TypeError(msg)

    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            msg = f"{label} must be a sequence of strings"
            raise TypeError(msg)
        normalized.append(item)
    return normalized


def _normalize_resolve(resolve: ResolveOption | None, /) -> dict[str, object] | None:
    if resolve is None:
        return None

    normalized = _normalize_string_key_mapping(resolve, label="Bundler.resolve")
    for key in ("conditionNames", "condition_names"):
        if key in normalized:
            normalized[key] = _normalize_string_sequence(
                normalized[key],
                label="Bundler.resolve.condition_names",
            )
    return normalized


def _normalize_devtools(devtools: DevtoolsOption | None, /) -> bool | dict[str, object] | None:
    if devtools is None or isinstance(devtools, bool):
        return devtools

    return _normalize_string_key_mapping(devtools, label="Bundler.devtools")


def _normalize_output(output: OutputOption | None, /) -> dict[str, object] | None:
    if output is None:
        return None

    normalized = _normalize_string_key_mapping(output, label="Bundler.output")
    for key in (
        "dir",
        "file",
        "entryFileNames",
        "entry_file_names",
        "chunkFileNames",
        "chunk_file_names",
        "assetFileNames",
        "asset_file_names",
    ):
        if key in normalized and isinstance(normalized[key], (str, PathLike)):
            normalized[key] = _normalize_string_path(
                normalized[key],
                label=f"Bundler.output.{key}",
            )
    return normalized


class Bundler(BundlerImpl):
    def __new__(
        cls,
        *,
        input: InputOption,  # noqa: A002
        cwd: str | PathLike[str] | None = None,
        resolve: ResolveOption | None = None,
        devtools: DevtoolsOption | None = None,
        output: OutputOption | None = None,
        plugins: object | None = None,
        watch: object | None = None,
    ) -> Self:
        return super().__new__(
            cls,
            input=_normalize_input(input),
            cwd=(None if cwd is None else _normalize_string_path(cwd, label="Bundler.cwd", absolute=True)),
            resolve=_normalize_resolve(resolve),
            devtools=_normalize_devtools(devtools),
            output=_normalize_output(output),
            plugins=plugins,
            watch=watch,
        )

    def __call__(self) -> BundlerContext:
        return BundlerContext(self)


class BundlerContext(BundlerContextImpl):
    def __new__(cls, bundler: Bundler, /) -> Self:
        return super().__new__(cls, bundler)

    def __init__(self, bundler: Bundler, /) -> None:
        self._bundler = bundler
        self._async_context: AsyncBundlerContext | None = None

    def __enter__(self) -> Self:
        if self._async_context is not None:
            raise RuntimeError(_BUNDLER_CONTEXT_ALREADY_ACTIVE)

        super().__enter__()
        return self

    async def __aenter__(self) -> AsyncBundlerContext:
        if self._async_context is not None:
            raise RuntimeError(_BUNDLER_CONTEXT_ALREADY_ACTIVE)

        self._ensure_inactive()
        async_context = AsyncBundlerContext(self._bundler)
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

    def __call__(
        self,
        output: OutputOption | None = None,
        /,
        *,
        write: bool | None = None,
    ) -> BundlerOutput:
        result = _call_bundler_context_impl(self, _normalize_output(output), write=write)
        return BundlerOutput._from_impl(result)


class AsyncBundlerContext(AsyncBundlerContextImpl):
    def __new__(cls, bundler: Bundler, /) -> Self:
        return super().__new__(cls, bundler)

    def __init__(self, bundler: Bundler, /) -> None:
        self._bundler = bundler

    async def __call__(
        self,
        output: OutputOption | None = None,
        /,
        *,
        write: bool | None = None,
    ) -> BundlerOutput:
        result = await _call_async_bundler_context_impl(
            self,
            _normalize_output(output),
            write=write,
        )
        return BundlerOutput._from_impl(result)
