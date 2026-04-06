from __future__ import annotations

from gdansk_bundler._core import (
    AsyncBundlerContext,
    Bundler,
    BundlerContext,
    BundlerOutput,
    OutputAsset,
    OutputChunk,
)
from gdansk_bundler.types import (
    CommentsOptions,
    GeneratedCodeOptions,
    InjectImportEntry,
    ManualCodeSplittingGroup,
    ManualCodeSplittingOptions,
    OutputOptions,
    ResolveAliasItem,
    ResolveExtensionAliasItem,
    ResolveOptions,
    TreeshakeOptions,
)

type OutputFile = OutputChunk | OutputAsset

__all__ = [
    "AsyncBundlerContext",
    "Bundler",
    "BundlerContext",
    "BundlerOutput",
    "CommentsOptions",
    "GeneratedCodeOptions",
    "InjectImportEntry",
    "ManualCodeSplittingGroup",
    "ManualCodeSplittingOptions",
    "OutputAsset",
    "OutputChunk",
    "OutputFile",
    "OutputOptions",
    "ResolveAliasItem",
    "ResolveExtensionAliasItem",
    "ResolveOptions",
    "TreeshakeOptions",
]
