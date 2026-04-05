# ruff: noqa: D100, D101, D102

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from gdansk_bundler._core import (
        BundlerOutput as BundlerOutputImpl,
        OutputAsset as OutputAssetImpl,
        OutputChunk as OutputChunkImpl,
    )

type OutputSource = str | bytes


@dataclass(slots=True, frozen=True)
class OutputChunk:
    name: str
    file_name: str
    code: str
    is_entry: bool
    is_dynamic_entry: bool
    facade_module_id: str | None
    module_ids: tuple[str, ...]
    exports: tuple[str, ...]
    imports: tuple[str, ...]
    dynamic_imports: tuple[str, ...]
    sourcemap: str | None
    sourcemap_file_name: str | None
    preliminary_file_name: str

    @classmethod
    def _from_impl(cls, chunk: OutputChunkImpl, /) -> Self:
        return cls(
            name=chunk.name,
            file_name=chunk.file_name,
            code=chunk.code,
            is_entry=chunk.is_entry,
            is_dynamic_entry=chunk.is_dynamic_entry,
            facade_module_id=chunk.facade_module_id,
            module_ids=tuple(chunk.module_ids),
            exports=tuple(chunk.exports),
            imports=tuple(chunk.imports),
            dynamic_imports=tuple(chunk.dynamic_imports),
            sourcemap=chunk.sourcemap,
            sourcemap_file_name=chunk.sourcemap_file_name,
            preliminary_file_name=chunk.preliminary_file_name,
        )


@dataclass(slots=True, frozen=True)
class OutputAsset:
    file_name: str
    names: tuple[str, ...]
    original_file_names: tuple[str, ...]
    source: OutputSource

    @classmethod
    def _from_impl(cls, asset: OutputAssetImpl, /) -> Self:
        return cls(
            file_name=asset.file_name,
            names=tuple(asset.names),
            original_file_names=tuple(asset.original_file_names),
            source=asset.source,
        )


type OutputFile = OutputChunk | OutputAsset


@dataclass(slots=True, frozen=True)
class BundlerOutput:
    chunks: tuple[OutputChunk, ...]
    assets: tuple[OutputAsset, ...]
    warnings: tuple[str, ...] = ()

    @classmethod
    def _from_impl(cls, output: BundlerOutputImpl, /) -> Self:
        return cls(
            chunks=tuple(OutputChunk._from_impl(chunk) for chunk in output.chunks),  # noqa: SLF001
            assets=tuple(OutputAsset._from_impl(asset) for asset in output.assets),  # noqa: SLF001
            warnings=tuple(output.warnings),
        )

    @property
    def files(self) -> tuple[OutputFile, ...]:
        return (*self.chunks, *self.assets)
