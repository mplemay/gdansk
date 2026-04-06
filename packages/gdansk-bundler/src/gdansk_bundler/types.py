from __future__ import annotations

from typing import Literal, TypedDict

# InjectImportEntry: list items use a required "from" key; named vs namespace shapes are documented on Bundler.inject.
type InjectImportEntry = dict[str, str | None]


class ResolveAliasItem(TypedDict):
    find: str
    replacements: list[str | None]


class ResolveExtensionAliasItem(TypedDict):
    target: str
    replacements: list[str]


class ResolveOptions(TypedDict, total=False):
    alias: list[ResolveAliasItem]
    extension_alias: list[ResolveExtensionAliasItem]
    alias_fields: list[list[str]]
    exports_fields: list[list[str]]
    condition_names: list[str]
    extensions: list[str]
    main_fields: list[str]
    main_files: list[str]
    modules: list[str]
    symlinks: bool
    yarn_pnp: bool


class TreeshakeOptions(TypedDict, total=False):
    module_side_effects: bool
    annotations: bool
    manual_pure_functions: list[str]
    unknown_global_side_effects: bool
    invalid_import_side_effects: bool
    commonjs: bool
    property_read_side_effects: Literal["always", "false"]
    property_write_side_effects: Literal["always", "false"]


class ManualCodeSplittingGroup(TypedDict, total=False):
    name: str
    test: str
    priority: int
    min_size: float
    max_size: float
    min_share_count: int
    min_module_size: float
    max_module_size: float
    entries_aware: bool
    entries_aware_merge_threshold: float


class ManualCodeSplittingOptions(TypedDict, total=False):
    min_share_count: int
    min_size: float
    max_size: float
    min_module_size: float
    max_module_size: float
    include_dependencies_recursively: bool
    groups: list[ManualCodeSplittingGroup]


class GeneratedCodeOptions(TypedDict, total=False):
    symbols: bool
    preset: Literal["es5", "es2015"]


class CommentsOptions(TypedDict, total=False):
    legal: bool
    annotation: bool
    jsdoc: bool


class OutputOptions(TypedDict, total=False):
    dir: str
    file: str
    format: Literal["es", "esm", "module", "cjs", "commonjs", "iife", "umd"]
    entry_file_names: str
    chunk_file_names: str
    asset_file_names: str
    sourcemap: bool | Literal["file", "inline", "hidden"]
    name: str
    banner: str
    post_banner: str
    footer: str
    post_footer: str
    intro: str
    outro: str
    globals: dict[str, str]
    paths: dict[str, str]
    exports: Literal["default", "named", "none", "auto"]
    es_module: bool | Literal["if-default-prop"]
    extend: bool
    external_live_bindings: bool
    inline_dynamic_imports: bool
    dynamic_import_in_cjs: bool
    hash_characters: Literal["base64", "base36", "hex"]
    generated_code: GeneratedCodeOptions
    sourcemap_base_url: str
    sourcemap_debug_ids: bool
    sourcemap_exclude_sources: bool
    strict: bool | Literal["auto"]
    legal_comments: Literal["none", "inline"]
    comments: bool | CommentsOptions
    polyfill_require: bool
    preserve_modules: bool
    virtual_dirname: str
    preserve_modules_root: str
    top_level_var: bool
    minify_internal_exports: bool
    clean_dir: bool
    strict_execution_order: bool
    minify: bool | Literal["dce-only", "dceOnly"]
    sanitize_file_name: bool
