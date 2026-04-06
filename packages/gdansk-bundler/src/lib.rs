use std::{path::PathBuf, sync::Arc};

use pyo3::{
    exceptions::{PyNotImplementedError, PyRuntimeError, PyTypeError, PyValueError},
    prelude::*,
    types::{PyBool, PyBytes, PyDict, PyList, PyString, PyTuple},
};
use rolldown::{
    AddonOutputOption, AssetFilenamesOutputOption, BundleOutput, Bundler as RolldownBundler,
    BundlerOptions, ChunkFilenamesOutputOption, CodeSplittingMode, CommentsOptions, DevtoolsOptions,
    EsModuleFlag, GeneratedCodeOptions, GlobalsOutputOption, HashCharacters, InjectImport, InputItem,
    InnerOptions, IsExternal, LegalComments, ManualCodeSplittingOptions, MatchGroup, MatchGroupName,
    MatchGroupTest, ModuleSideEffects, OutputExports, OutputFormat, PathsOutputOption, Platform,
    PropertyReadSideEffects, PropertyWriteSideEffects, RawMinifyOptions, ResolveOptions,
    SanitizeFilename, SourceMapType, StrictMode, TreeshakeOptions, TsConfig,
};
use rolldown_utils::{indexmap::FxIndexMap, pattern_filter::StringOrRegex};
use rustc_hash::{FxHashMap, FxHashSet};

const BUNDLER_CONTEXT_ALREADY_ACTIVE: &str = "BundlerContext is already active";
const BUNDLER_CONTEXT_NOT_ACTIVE: &str = "BundlerContext is not active";
const FIRST_MILESTONE_MESSAGE: &str =
    "is not supported in the first gdansk-bundler milestone";

#[derive(Clone, Debug)]
struct BundlerConfigState {
    input: Vec<InputItem>,
    cwd: Option<PathBuf>,
    resolve: Option<ResolveOptions>,
    devtools_enabled: bool,
    devtools_session_id: Option<String>,
    default_output: Option<OutputConfig>,
    platform: Option<Platform>,
    context: Option<String>,
    tsconfig: Option<TsConfig>,
    shim_missing_exports: Option<bool>,
    keep_names: Option<bool>,
    profiler_names: Option<bool>,
    define: Option<FxIndexMap<String, String>>,
    drop_labels: Option<Vec<String>>,
    inject: Option<Vec<InjectImport>>,
    external: Option<IsExternal>,
    treeshake: Option<TreeshakeOptions>,
    manual_code_splitting: Option<ManualCodeSplittingOptions>,
}

#[derive(Clone, Debug, Default)]
struct OutputConfig {
    dir: Option<String>,
    file: Option<String>,
    format: Option<OutputFormat>,
    entry_file_names: Option<String>,
    chunk_file_names: Option<String>,
    asset_file_names: Option<String>,
    sourcemap: Option<SourcemapSetting>,
    name: Option<String>,
    banner: Option<String>,
    post_banner: Option<String>,
    footer: Option<String>,
    post_footer: Option<String>,
    intro: Option<String>,
    outro: Option<String>,
    globals: Option<FxHashMap<String, String>>,
    paths: Option<FxHashMap<String, String>>,
    exports: Option<OutputExports>,
    es_module: Option<EsModuleFlag>,
    extend: Option<bool>,
    external_live_bindings: Option<bool>,
    inline_dynamic_imports: Option<bool>,
    dynamic_import_in_cjs: Option<bool>,
    hash_characters: Option<HashCharacters>,
    generated_code: Option<GeneratedCodeOptions>,
    sourcemap_base_url: Option<String>,
    sourcemap_debug_ids: Option<bool>,
    sourcemap_exclude_sources: Option<bool>,
    strict: Option<StrictMode>,
    legal_comments: Option<LegalComments>,
    comments: Option<CommentsOptions>,
    polyfill_require: Option<bool>,
    preserve_modules: Option<bool>,
    virtual_dirname: Option<String>,
    preserve_modules_root: Option<String>,
    top_level_var: Option<bool>,
    minify_internal_exports: Option<bool>,
    clean_dir: Option<bool>,
    strict_execution_order: Option<bool>,
    minify: Option<RawMinifyOptions>,
    sanitize_file_name: Option<SanitizeFilename>,
}

#[derive(Clone, Debug)]
enum SourcemapSetting {
    Disabled,
    Enabled(SourceMapType),
}

#[derive(Clone, Debug)]
enum OutputAssetSource {
    String(String),
    Bytes(Vec<u8>),
}

#[pyclass(module = "gdansk_bundler._core", frozen, skip_from_py_object)]
struct Bundler {
    config: Arc<BundlerConfigState>,
}

#[pyclass(module = "gdansk_bundler._core", unsendable, skip_from_py_object)]
struct BundlerContext {
    config: Arc<BundlerConfigState>,
    active: bool,
}

#[pyclass(module = "gdansk_bundler._core", skip_from_py_object)]
struct AsyncBundlerContext {
    config: Arc<BundlerConfigState>,
    active: bool,
}

#[pyclass(module = "gdansk_bundler._core", frozen, skip_from_py_object)]
#[derive(Clone, Debug)]
struct OutputChunk {
    name: String,
    file_name: String,
    code: String,
    is_entry: bool,
    is_dynamic_entry: bool,
    facade_module_id: Option<String>,
    module_ids: Vec<String>,
    exports: Vec<String>,
    imports: Vec<String>,
    dynamic_imports: Vec<String>,
    sourcemap: Option<String>,
    sourcemap_file_name: Option<String>,
    preliminary_file_name: String,
}

#[pyclass(module = "gdansk_bundler._core", frozen, skip_from_py_object)]
#[derive(Clone, Debug)]
struct OutputAsset {
    file_name: String,
    names: Vec<String>,
    original_file_names: Vec<String>,
    source: OutputAssetSource,
}

#[pyclass(module = "gdansk_bundler._core", frozen, skip_from_py_object)]
#[derive(Clone, Debug)]
struct BundlerOutput {
    chunks: Vec<OutputChunk>,
    assets: Vec<OutputAsset>,
    warnings: Vec<String>,
}

fn unsupported_feature_error(path: &str) -> PyErr {
    PyNotImplementedError::new_err(format!("{path} {FIRST_MILESTONE_MESSAGE}"))
}

fn extract_string(value: &Bound<'_, PyAny>, message: &str) -> PyResult<String> {
    Ok(value
        .cast::<PyString>()
        .map_err(|_| PyTypeError::new_err(message.to_owned()))?
        .to_str()?
        .to_owned())
}

fn extract_path_as_string(value: &Bound<'_, PyAny>, message: &str) -> PyResult<String> {
    let path: PathBuf = value
        .extract()
        .map_err(|_| PyTypeError::new_err(message.to_owned()))?;
    Ok(path.to_string_lossy().into_owned())
}

fn parse_optional_cwd(value: Option<&Bound<'_, PyAny>>) -> PyResult<Option<PathBuf>> {
    let Some(value) = value else {
        return Ok(None);
    };
    let path: PathBuf = value.extract().map_err(|_| {
        PyTypeError::new_err("Bundler.cwd must be a string path or os.PathLike path")
    })?;
    if path.is_absolute() {
        return Ok(Some(path));
    }
    let base = std::env::current_dir().map_err(|err| {
        PyRuntimeError::new_err(format!("failed to read current working directory: {err}"))
    })?;
    Ok(Some(base.join(path)))
}

fn extract_string_sequence(value: &Bound<'_, PyAny>, message: &str) -> PyResult<Vec<String>> {
    if let Ok(list) = value.cast::<PyList>() {
        return list.iter().map(|item| extract_string(&item, message)).collect();
    }

    if let Ok(tuple) = value.cast::<PyTuple>() {
        return tuple.iter().map(|item| extract_string(&item, message)).collect();
    }

    Err(PyTypeError::new_err(message.to_owned()))
}

fn get_mapping_item<'py>(
    mapping: &Bound<'py, PyDict>,
    keys: &[&str],
) -> PyResult<Option<Bound<'py, PyAny>>> {
    for key in keys {
        if let Some(value) = mapping.get_item(key)? {
            return Ok(Some(value));
        }
    }

    Ok(None)
}

fn ensure_supported_mapping_fields(
    mapping: &Bound<'_, PyDict>,
    container: &str,
    allowed: &[&str],
) -> PyResult<()> {
    for (key, _) in mapping.iter() {
        let key = key
            .cast::<PyString>()
            .map_err(|_| PyTypeError::new_err(format!("{container} keys must be strings")))?;
        let key = key.to_str()?;
        if !allowed.contains(&key) {
            return Err(unsupported_feature_error(&format!("{container}.{key}")));
        }
    }

    Ok(())
}

fn parse_output_format(value: &Bound<'_, PyAny>, message: &str) -> PyResult<OutputFormat> {
    let value = extract_string(value, message)?;
    match value.as_str() {
        "es" | "esm" | "module" => Ok(OutputFormat::Esm),
        "cjs" | "commonjs" => Ok(OutputFormat::Cjs),
        "iife" => Ok(OutputFormat::Iife),
        "umd" => Ok(OutputFormat::Umd),
        _ => Err(PyValueError::new_err(message.to_owned())),
    }
}

fn parse_sourcemap_setting(
    value: &Bound<'_, PyAny>,
    message: &str,
) -> PyResult<SourcemapSetting> {
    if value.is_instance_of::<PyBool>() {
        return Ok(if value.cast::<PyBool>()?.extract::<bool>()? {
            SourcemapSetting::Enabled(SourceMapType::File)
        } else {
            SourcemapSetting::Disabled
        });
    }

    let value = extract_string(value, message)?;
    match value.as_str() {
        "file" => Ok(SourcemapSetting::Enabled(SourceMapType::File)),
        "inline" => Ok(SourcemapSetting::Enabled(SourceMapType::Inline)),
        "hidden" => Ok(SourcemapSetting::Enabled(SourceMapType::Hidden)),
        _ => Err(PyValueError::new_err(message.to_owned())),
    }
}

fn parse_input(value: &Bound<'_, PyAny>) -> PyResult<Vec<InputItem>> {
    let message = "Bundler.input must be a path, a sequence of paths, or a mapping of entry names to paths (str or os.PathLike)";

    if value.is_instance_of::<PyString>() {
        let input = extract_path_as_string(value, message)?;
        return Ok(vec![InputItem::from(input)]);
    }

    if let Ok(list) = value.cast::<PyList>() {
        let input = list
            .iter()
            .map(|item| extract_path_as_string(&item, message).map(InputItem::from))
            .collect::<PyResult<Vec<_>>>()?;
        if input.is_empty() {
            return Err(PyValueError::new_err("Bundler.input must not be empty"));
        }
        return Ok(input);
    }

    if let Ok(tuple) = value.cast::<PyTuple>() {
        let input = tuple
            .iter()
            .map(|item| extract_path_as_string(&item, message).map(InputItem::from))
            .collect::<PyResult<Vec<_>>>()?;
        if input.is_empty() {
            return Err(PyValueError::new_err("Bundler.input must not be empty"));
        }
        return Ok(input);
    }

    if let Ok(mapping) = value.cast::<PyDict>() {
        let input = mapping
            .iter()
            .map(|(key, item)| {
                let key = extract_string(&key, "Bundler.input mapping keys must be strings")?;
                let import = extract_path_as_string(&item, message)?;
                Ok(InputItem {
                    name: Some(key),
                    import,
                })
            })
            .collect::<PyResult<Vec<_>>>()?;
        if input.is_empty() {
            return Err(PyValueError::new_err("Bundler.input must not be empty"));
        }
        return Ok(input);
    }

    let input = extract_path_as_string(value, message)?;
    Ok(vec![InputItem::from(input)])
}

fn parse_nested_string_matrix(
    value: &Bound<'_, PyAny>,
    message: &str,
) -> PyResult<Vec<Vec<String>>> {
    let list = value
        .cast::<PyList>()
        .map_err(|_| PyTypeError::new_err(message.to_owned()))?;
    list
        .iter()
        .map(|row| extract_string_sequence(&row, message))
        .collect()
}

fn parse_optional_string_matrix(
    value: Option<Bound<'_, PyAny>>,
    message: &str,
) -> PyResult<Option<Vec<Vec<String>>>> {
    value
        .map(|v| parse_nested_string_matrix(&v, message))
        .transpose()
}

fn parse_resolve_alias_item(
    item: &Bound<'_, PyAny>,
    container: &str,
) -> PyResult<(String, Vec<Option<String>>)> {
    let mapping = item
        .cast::<PyDict>()
        .map_err(|_| PyTypeError::new_err(format!("{container} items must be mappings")))?;
    ensure_supported_mapping_fields(mapping, container, &["find", "replacements"])?;
    let find = get_mapping_item(mapping, &["find"])?
        .ok_or_else(|| PyValueError::new_err(format!("{container}.find is required")))?;
    let find = extract_string(&find, &format!("{container}.find must be a string"))?;
    let replacements = get_mapping_item(mapping, &["replacements"])?
        .ok_or_else(|| PyValueError::new_err(format!("{container}.replacements is required")))?;
    let repl_list = replacements
        .cast::<PyList>()
        .map_err(|_| {
            PyTypeError::new_err(format!("{container}.replacements must be a list"))
        })?;
    let mut out = Vec::new();
    for entry in repl_list.iter() {
        if entry.is_none() {
            out.push(None);
        } else {
            out.push(Some(extract_string(
                &entry,
                &format!("{container}.replacements entries must be strings or None"),
            )?));
        }
    }
    Ok((find, out))
}

fn parse_extension_alias_item(
    item: &Bound<'_, PyAny>,
    container: &str,
) -> PyResult<(String, Vec<String>)> {
    let mapping = item
        .cast::<PyDict>()
        .map_err(|_| PyTypeError::new_err(format!("{container} items must be mappings")))?;
    ensure_supported_mapping_fields(mapping, container, &["target", "replacements"])?;
    let target = get_mapping_item(mapping, &["target"])?
        .ok_or_else(|| PyValueError::new_err(format!("{container}.target is required")))?;
    let target = extract_string(&target, &format!("{container}.target must be a string"))?;
    let replacements = get_mapping_item(mapping, &["replacements"])?
        .ok_or_else(|| PyValueError::new_err(format!("{container}.replacements is required")))?;
    let seq = extract_string_sequence(
        &replacements,
        &format!("{container}.replacements must be a sequence of strings"),
    )?;
    Ok((target, seq))
}

fn parse_resolve_options(resolve: Option<&Bound<'_, PyAny>>) -> PyResult<Option<ResolveOptions>> {
    let Some(resolve) = resolve else {
        return Ok(None);
    };
    let mapping = resolve
        .cast::<PyDict>()
        .map_err(|_| PyTypeError::new_err("Bundler.resolve must be a mapping"))?;
    ensure_supported_mapping_fields(
        mapping,
        "Bundler.resolve",
        &[
            "alias",
            "aliasFields",
            "alias_fields",
            "conditionNames",
            "condition_names",
            "exportsFields",
            "exports_fields",
            "extensions",
            "extensionAlias",
            "extension_alias",
            "mainFields",
            "main_fields",
            "mainFiles",
            "main_files",
            "modules",
            "symlinks",
            "yarnPnp",
            "yarn_pnp",
        ],
    )?;

    let alias = get_mapping_item(mapping, &["alias"])?
        .map(|value| {
            let list = value.cast::<PyList>().map_err(|_| {
                PyTypeError::new_err("Bundler.resolve.alias must be a list of alias items")
            })?;
            list
                .iter()
                .map(|item| parse_resolve_alias_item(&item, "Bundler.resolve.alias[]"))
                .collect::<PyResult<Vec<_>>>()
        })
        .transpose()?;

    let extension_alias = get_mapping_item(mapping, &["extensionAlias", "extension_alias"])?
        .map(|value| {
            let list = value.cast::<PyList>().map_err(|_| {
                PyTypeError::new_err(
                    "Bundler.resolve.extension_alias must be a list of extension alias items",
                )
            })?;
            list
                .iter()
                .map(|item| {
                    parse_extension_alias_item(&item, "Bundler.resolve.extension_alias[]")
                })
                .collect::<PyResult<Vec<_>>>()
        })
        .transpose()?;

    let alias_fields = parse_optional_string_matrix(
        get_mapping_item(mapping, &["aliasFields", "alias_fields"])?,
        "Bundler.resolve.alias_fields rows must be sequences of strings",
    )?;

    let exports_fields = parse_optional_string_matrix(
        get_mapping_item(mapping, &["exportsFields", "exports_fields"])?,
        "Bundler.resolve.exports_fields rows must be sequences of strings",
    )?;

    let condition_names = get_mapping_item(mapping, &["conditionNames", "condition_names"])?
        .map(|value| {
            extract_string_sequence(
                &value,
                "Bundler.resolve.condition_names must be a sequence of strings",
            )
        })
        .transpose()?;

    let extensions = get_mapping_item(mapping, &["extensions"])?
        .map(|value| {
            extract_string_sequence(
                &value,
                "Bundler.resolve.extensions must be a sequence of strings",
            )
        })
        .transpose()?;

    let main_fields = get_mapping_item(mapping, &["mainFields", "main_fields"])?
        .map(|value| {
            extract_string_sequence(
                &value,
                "Bundler.resolve.main_fields must be a sequence of strings",
            )
        })
        .transpose()?;

    let main_files = get_mapping_item(mapping, &["mainFiles", "main_files"])?
        .map(|value| {
            extract_string_sequence(
                &value,
                "Bundler.resolve.main_files must be a sequence of strings",
            )
        })
        .transpose()?;

    let modules = get_mapping_item(mapping, &["modules"])?
        .map(|value| {
            extract_string_sequence(
                &value,
                "Bundler.resolve.modules must be a sequence of strings",
            )
        })
        .transpose()?;

    let symlinks = get_mapping_item(mapping, &["symlinks"])?
        .map(|v| {
            v.cast::<PyBool>()
                .map_err(|_| PyTypeError::new_err("Bundler.resolve.symlinks must be a boolean"))?
                .extract()
        })
        .transpose()?;

    let yarn_pnp = get_mapping_item(mapping, &["yarnPnp", "yarn_pnp"])?
        .map(|v| {
            v.cast::<PyBool>()
                .map_err(|_| PyTypeError::new_err("Bundler.resolve.yarn_pnp must be a boolean"))?
                .extract()
        })
        .transpose()?;

    if alias.is_none()
        && extension_alias.is_none()
        && alias_fields.is_none()
        && exports_fields.is_none()
        && condition_names.is_none()
        && extensions.is_none()
        && main_fields.is_none()
        && main_files.is_none()
        && modules.is_none()
        && symlinks.is_none()
        && yarn_pnp.is_none()
    {
        return Ok(None);
    }

    Ok(Some(ResolveOptions {
        alias,
        extension_alias,
        alias_fields,
        exports_fields,
        condition_names,
        extensions,
        main_fields,
        main_files,
        modules,
        symlinks,
        yarn_pnp,
    }))
}

fn python_regex_flags_to_js(flags: i32) -> String {
    let mut s = String::new();
    if flags & 2 != 0 {
        s.push('i');
    }
    if flags & 4 != 0 {
        s.push('l');
    }
    if flags & 8 != 0 {
        s.push('m');
    }
    if flags & 16 != 0 {
        s.push('s');
    }
    if flags & 32 != 0 {
        s.push('u');
    }
    s
}

fn parse_external_pattern_item(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    message: &str,
) -> PyResult<StringOrRegex> {
    if value.is_instance_of::<PyString>() {
        return Ok(StringOrRegex::String(extract_string(value, message)?));
    }

    let re_mod = py.import("re").map_err(|_| {
        PyRuntimeError::new_err("failed to import Python re module for external patterns")
    })?;
    let pattern_cls = re_mod.getattr("Pattern").map_err(|_| {
        PyRuntimeError::new_err("failed to load re.Pattern for external patterns")
    })?;
    if value.is_instance(&pattern_cls)? {
        let pat: String = value.getattr("pattern")?.extract()?;
        let flags: i32 = value.getattr("flags")?.extract().unwrap_or(0);
        let js_flags = python_regex_flags_to_js(flags);
        let regex = if js_flags.is_empty() {
            rolldown_utils::js_regex::HybridRegex::new(&pat)
        } else {
            rolldown_utils::js_regex::HybridRegex::with_flags(&pat, &js_flags)
        }
        .map_err(|e| PyValueError::new_err(format!("invalid external regex: {e}")))?;
        return Ok(StringOrRegex::Regex(regex));
    }

    if let Ok(tuple) = value.cast::<PyTuple>()
        && tuple.len() == 2
    {
        let pat = extract_string(&tuple.get_item(0)?, message)?;
        let flags = extract_string(&tuple.get_item(1)?, message)?;
        let regex = rolldown_utils::js_regex::HybridRegex::with_flags(&pat, &flags)
            .map_err(|e| PyValueError::new_err(format!("invalid external regex: {e}")))?;
        return Ok(StringOrRegex::Regex(regex));
    }

    Err(PyTypeError::new_err(message.to_owned()))
}

fn parse_external(py: Python<'_>, value: Option<&Bound<'_, PyAny>>) -> PyResult<Option<IsExternal>> {
    let Some(value) = value else {
        return Ok(None);
    };
    let message = "Bundler.external entries must be str, re.Pattern, or (pattern, flags) tuples";
    let mut patterns = Vec::new();
    if let Ok(list) = value.cast::<PyList>() {
        for item in list.iter() {
            patterns.push(parse_external_pattern_item(py, &item, message)?);
        }
    } else if let Ok(tuple) = value.cast::<PyTuple>() {
        for item in tuple.iter() {
            patterns.push(parse_external_pattern_item(py, &item, message)?);
        }
    } else {
        patterns.push(parse_external_pattern_item(py, value, message)?);
    }
    Ok(Some(IsExternal::StringOrRegex(patterns)))
}

fn parse_define(value: Option<&Bound<'_, PyAny>>) -> PyResult<Option<FxIndexMap<String, String>>> {
    let Some(value) = value else {
        return Ok(None);
    };
    if let Ok(mapping) = value.cast::<PyDict>() {
        let mut map = FxIndexMap::default();
        for (k, v) in mapping.iter() {
            let key = extract_string(&k, "Bundler.define keys must be strings")?;
            let val = extract_string(&v, "Bundler.define values must be strings")?;
            map.insert(key, val);
        }
        return Ok(Some(map));
    }
    let list = value
        .cast::<PyList>()
        .map_err(|_| PyTypeError::new_err("Bundler.define must be a dict or a list of pairs"))?;
    let mut map = FxIndexMap::default();
    for item in list.iter() {
        let pair = item.cast::<PyTuple>().map_err(|_| {
            PyTypeError::new_err("Bundler.define list entries must be (key, value) tuples")
        })?;
        if pair.len() != 2 {
            return Err(PyValueError::new_err(
                "Bundler.define list entries must be (key, value) tuples",
            ));
        }
        let key = extract_string(&pair.get_item(0)?, "Bundler.define pair keys must be strings")?;
        let val = extract_string(&pair.get_item(1)?, "Bundler.define pair values must be strings")?;
        map.insert(key, val);
    }
    Ok(Some(map))
}

fn parse_inject(value: Option<&Bound<'_, PyAny>>) -> PyResult<Option<Vec<InjectImport>>> {
    let Some(value) = value else {
        return Ok(None);
    };
    let list = value
        .cast::<PyList>()
        .map_err(|_| PyTypeError::new_err("Bundler.inject must be a list of inject import mappings"))?;
    let mut out = Vec::with_capacity(list.len());
    for item in list.iter() {
        let mapping = item
            .cast::<PyDict>()
            .map_err(|_| PyTypeError::new_err("Bundler.inject entries must be mappings"))?;
        ensure_supported_mapping_fields(
            mapping,
            "Bundler.inject[]",
            &["imported", "from", "alias"],
        )?;
        let imported = get_mapping_item(mapping, &["imported"])?;
        let from = get_mapping_item(mapping, &["from"])?
            .ok_or_else(|| PyValueError::new_err("Bundler.inject[].from is required"))?;
        let from = extract_string(&from, "Bundler.inject[].from must be a string")?;
        if let Some(imported) = imported {
            let imported =
                extract_string(&imported, "Bundler.inject[].imported must be a string")?;
            let alias = get_mapping_item(mapping, &["alias"])?
                .map(|a| extract_string(&a, "Bundler.inject[].alias must be a string"))
                .transpose()?;
            out.push(InjectImport::Named { imported, alias, from });
        } else {
            let alias = get_mapping_item(mapping, &["alias"])?
                .ok_or_else(|| PyValueError::new_err("namespace inject requires alias and from"))?;
            let alias = extract_string(&alias, "Bundler.inject[].alias must be a string")?;
            out.push(InjectImport::Namespace { alias, from });
        }
    }
    Ok(Some(out))
}

fn parse_tsconfig(value: Option<&Bound<'_, PyAny>>) -> PyResult<Option<TsConfig>> {
    let Some(value) = value else {
        return Ok(None);
    };
    if value.is_instance_of::<PyBool>() {
        return Ok(Some(TsConfig::Auto(
            value.cast::<PyBool>()?.extract::<bool>()?,
        )));
    }
    let path = extract_path_as_string(
        value,
        "Bundler.tsconfig path must be a string path or os.PathLike path",
    )?;
    Ok(Some(TsConfig::Manual(PathBuf::from(path))))
}

fn parse_platform(value: Option<&Bound<'_, PyAny>>) -> PyResult<Option<Platform>> {
    let Some(value) = value else {
        return Ok(None);
    };
    let s = extract_string(
        value,
        "Bundler.platform must be 'node', 'browser', or 'neutral'",
    )?;
    Platform::try_from(s.as_str())
        .map(Some)
        .map_err(PyValueError::new_err)
}

fn parse_property_read_side_effects(
    value: &Bound<'_, PyAny>,
    label: &str,
) -> PyResult<PropertyReadSideEffects> {
    let s = extract_string(
        value,
        &format!("{label} must be 'always' or 'false'"),
    )?;
    match s.as_str() {
        "always" => Ok(PropertyReadSideEffects::Always),
        "false" => Ok(PropertyReadSideEffects::False),
        _ => Err(PyValueError::new_err(format!(
            "{label} must be 'always' or 'false'"
        ))),
    }
}

fn parse_property_write_side_effects(
    value: &Bound<'_, PyAny>,
    label: &str,
) -> PyResult<PropertyWriteSideEffects> {
    let s = extract_string(
        value,
        &format!("{label} must be 'always' or 'false'"),
    )?;
    match s.as_str() {
        "always" => Ok(PropertyWriteSideEffects::Always),
        "false" => Ok(PropertyWriteSideEffects::False),
        _ => Err(PyValueError::new_err(format!(
            "{label} must be 'always' or 'false'"
        ))),
    }
}

fn parse_treeshake(value: Option<&Bound<'_, PyAny>>) -> PyResult<Option<TreeshakeOptions>> {
    let Some(value) = value else {
        return Ok(None);
    };
    if value.is_instance_of::<PyBool>() {
        return Ok(Some(TreeshakeOptions::Boolean(
            value.cast::<PyBool>()?.extract::<bool>()?,
        )));
    }
    let mapping = value
        .cast::<PyDict>()
        .map_err(|_| PyTypeError::new_err("Bundler.treeshake must be a bool or a mapping"))?;
    ensure_supported_mapping_fields(
        mapping,
        "Bundler.treeshake",
        &[
            "moduleSideEffects",
            "module_side_effects",
            "annotations",
            "manualPureFunctions",
            "manual_pure_functions",
            "unknownGlobalSideEffects",
            "unknown_global_side_effects",
            "invalidImportSideEffects",
            "invalid_import_side_effects",
            "commonjs",
            "propertyReadSideEffects",
            "property_read_side_effects",
            "propertyWriteSideEffects",
            "property_write_side_effects",
        ],
    )?;

    let module_side_effects = get_mapping_item(mapping, &["moduleSideEffects", "module_side_effects"])?
        .map(|v| {
            if v.is_instance_of::<PyBool>() {
                Ok(if v.cast::<PyBool>()?.extract::<bool>()? {
                    ModuleSideEffects::Boolean(true)
                } else {
                    ModuleSideEffects::Boolean(false)
                })
            } else {
                Err(PyTypeError::new_err(
                    "Bundler.treeshake.module_side_effects must be a boolean",
                ))
            }
        })
        .transpose()?
        .unwrap_or(ModuleSideEffects::Boolean(true));

    let annotations = get_mapping_item(mapping, &["annotations"])?
        .map(|v| {
            v.cast::<PyBool>()
                .map_err(|_| PyTypeError::new_err("Bundler.treeshake.annotations must be a boolean"))?
                .extract()
        })
        .transpose()?;

    let manual_pure_functions = get_mapping_item(
        mapping,
        &["manualPureFunctions", "manual_pure_functions"],
    )?
    .map(|v| {
        let strings = extract_string_sequence(
            &v,
            "Bundler.treeshake.manual_pure_functions must be a sequence of strings",
        )?;
        Ok::<_, PyErr>(strings.into_iter().collect::<FxHashSet<_>>())
    })
    .transpose()?;

    let unknown_global_side_effects =
        get_mapping_item(mapping, &["unknownGlobalSideEffects", "unknown_global_side_effects"])?
            .map(|v| {
                v.cast::<PyBool>()
                    .map_err(|_| {
                        PyTypeError::new_err(
                            "Bundler.treeshake.unknown_global_side_effects must be a boolean",
                        )
                    })?
                    .extract()
            })
            .transpose()?;

    let invalid_import_side_effects =
        get_mapping_item(mapping, &["invalidImportSideEffects", "invalid_import_side_effects"])?
            .map(|v| {
                v.cast::<PyBool>()
                    .map_err(|_| {
                        PyTypeError::new_err(
                            "Bundler.treeshake.invalid_import_side_effects must be a boolean",
                        )
                    })?
                    .extract()
            })
            .transpose()?;

    let commonjs = get_mapping_item(mapping, &["commonjs"])?
        .map(|v| {
            v.cast::<PyBool>()
                .map_err(|_| PyTypeError::new_err("Bundler.treeshake.commonjs must be a boolean"))?
                .extract()
        })
        .transpose()?;

    let property_read_side_effects = get_mapping_item(
        mapping,
        &["propertyReadSideEffects", "property_read_side_effects"],
    )?
    .map(|v| parse_property_read_side_effects(&v, "Bundler.treeshake.property_read_side_effects"))
    .transpose()?;

    let property_write_side_effects = get_mapping_item(
        mapping,
        &["propertyWriteSideEffects", "property_write_side_effects"],
    )?
    .map(|v| parse_property_write_side_effects(&v, "Bundler.treeshake.property_write_side_effects"))
    .transpose()?;

    Ok(Some(TreeshakeOptions::Option(InnerOptions {
        module_side_effects,
        annotations,
        manual_pure_functions,
        unknown_global_side_effects,
        commonjs,
        property_read_side_effects,
        property_write_side_effects,
        invalid_import_side_effects,
    })))
}

fn parse_match_group(item: &Bound<'_, PyAny>, label: &str) -> PyResult<MatchGroup> {
    let mapping = item
        .cast::<PyDict>()
        .map_err(|_| PyTypeError::new_err(format!("{label} items must be mappings")))?;
    ensure_supported_mapping_fields(
        mapping,
        label,
        &[
            "name",
            "test",
            "priority",
            "minSize",
            "min_size",
            "maxSize",
            "max_size",
            "minShareCount",
            "min_share_count",
            "minModuleSize",
            "min_module_size",
            "maxModuleSize",
            "max_module_size",
            "entriesAware",
            "entries_aware",
            "entriesAwareMergeThreshold",
            "entries_aware_merge_threshold",
        ],
    )?;
    let name = get_mapping_item(mapping, &["name"])?
        .ok_or_else(|| PyValueError::new_err(format!("{label}.name is required")))?;
    let name = extract_string(&name, &format!("{label}.name must be a string"))?;
    let test = get_mapping_item(mapping, &["test"])?
        .map(|v| {
            let pat = extract_string(&v, &format!("{label}.test must be a regex pattern string"))?;
            let r = rolldown_utils::js_regex::HybridRegex::new(&pat)
                .map_err(|e| PyValueError::new_err(format!("invalid {label}.test regex: {e}")))?;
            Ok::<_, PyErr>(MatchGroupTest::Regex(r))
        })
        .transpose()?;
    let priority = get_mapping_item(mapping, &["priority"])?
        .map(|v| {
            v.extract::<u32>()
                .map_err(|_| PyTypeError::new_err(format!("{label}.priority must be an int")))
        })
        .transpose()?;
    let min_size = get_mapping_item(mapping, &["minSize", "min_size"])?
        .map(|v| {
            v.extract::<f64>()
                .map_err(|_| PyTypeError::new_err(format!("{label}.min_size must be a float")))
        })
        .transpose()?;
    let max_size = get_mapping_item(mapping, &["maxSize", "max_size"])?
        .map(|v| {
            v.extract::<f64>()
                .map_err(|_| PyTypeError::new_err(format!("{label}.max_size must be a float")))
        })
        .transpose()?;
    let min_share_count = get_mapping_item(mapping, &["minShareCount", "min_share_count"])?
        .map(|v| {
            v.extract::<u32>().map_err(|_| {
                PyTypeError::new_err(format!("{label}.min_share_count must be an int"))
            })
        })
        .transpose()?;
    let min_module_size = get_mapping_item(mapping, &["minModuleSize", "min_module_size"])?
        .map(|v| {
            v.extract::<f64>().map_err(|_| {
                PyTypeError::new_err(format!("{label}.min_module_size must be a float"))
            })
        })
        .transpose()?;
    let max_module_size = get_mapping_item(mapping, &["maxModuleSize", "max_module_size"])?
        .map(|v| {
            v.extract::<f64>().map_err(|_| {
                PyTypeError::new_err(format!("{label}.max_module_size must be a float"))
            })
        })
        .transpose()?;
    let entries_aware = get_mapping_item(mapping, &["entriesAware", "entries_aware"])?
        .map(|v| {
            v.cast::<PyBool>()
                .map_err(|_| PyTypeError::new_err(format!("{label}.entries_aware must be a boolean")))?
                .extract()
        })
        .transpose()?;
    let entries_aware_merge_threshold = get_mapping_item(
        mapping,
        &["entriesAwareMergeThreshold", "entries_aware_merge_threshold"],
    )?
    .map(|v| {
        v.extract::<f64>().map_err(|_| {
            PyTypeError::new_err(format!(
                "{label}.entries_aware_merge_threshold must be a float"
            ))
        })
    })
    .transpose()?;

    Ok(MatchGroup {
        name: MatchGroupName::Static(name),
        test,
        priority,
        min_size,
        max_size,
        min_share_count,
        min_module_size,
        max_module_size,
        entries_aware,
        entries_aware_merge_threshold,
    })
}

fn parse_manual_code_splitting(
    value: Option<&Bound<'_, PyAny>>,
) -> PyResult<Option<ManualCodeSplittingOptions>> {
    let Some(value) = value else {
        return Ok(None);
    };
    let mapping = value
        .cast::<PyDict>()
        .map_err(|_| PyTypeError::new_err("Bundler.manual_code_splitting must be a mapping"))?;
    ensure_supported_mapping_fields(
        mapping,
        "Bundler.manual_code_splitting",
        &[
            "minShareCount",
            "min_share_count",
            "minSize",
            "min_size",
            "maxSize",
            "max_size",
            "minModuleSize",
            "min_module_size",
            "maxModuleSize",
            "max_module_size",
            "includeDependenciesRecursively",
            "include_dependencies_recursively",
            "groups",
        ],
    )?;

    let min_share_count = get_mapping_item(mapping, &["minShareCount", "min_share_count"])?
        .map(|v| {
            v.extract::<u32>().map_err(|_| {
                PyTypeError::new_err("Bundler.manual_code_splitting.min_share_count must be an int")
            })
        })
        .transpose()?;
    let min_size = get_mapping_item(mapping, &["minSize", "min_size"])?
        .map(|v| {
            v.extract::<f64>()
                .map_err(|_| PyTypeError::new_err("Bundler.manual_code_splitting.min_size must be a float"))
        })
        .transpose()?;
    let max_size = get_mapping_item(mapping, &["maxSize", "max_size"])?
        .map(|v| {
            v.extract::<f64>()
                .map_err(|_| PyTypeError::new_err("Bundler.manual_code_splitting.max_size must be a float"))
        })
        .transpose()?;
    let min_module_size = get_mapping_item(mapping, &["minModuleSize", "min_module_size"])?
        .map(|v| {
            v.extract::<f64>().map_err(|_| {
                PyTypeError::new_err("Bundler.manual_code_splitting.min_module_size must be a float")
            })
        })
        .transpose()?;
    let max_module_size = get_mapping_item(mapping, &["maxModuleSize", "max_module_size"])?
        .map(|v| {
            v.extract::<f64>().map_err(|_| {
                PyTypeError::new_err("Bundler.manual_code_splitting.max_module_size must be a float")
            })
        })
        .transpose()?;
    let include_dependencies_recursively = get_mapping_item(
        mapping,
        &["includeDependenciesRecursively", "include_dependencies_recursively"],
    )?
    .map(|v| {
        v.cast::<PyBool>()
            .map_err(|_| {
                PyTypeError::new_err(
                    "Bundler.manual_code_splitting.include_dependencies_recursively must be a boolean",
                )
            })?
            .extract()
    })
    .transpose()?;

    let groups = get_mapping_item(mapping, &["groups"])?
        .map(|v| {
            let list = v.cast::<PyList>().map_err(|_| {
                PyTypeError::new_err("Bundler.manual_code_splitting.groups must be a list")
            })?;
            list
                .iter()
                .map(|item| parse_match_group(&item, "Bundler.manual_code_splitting.groups[]"))
                .collect::<PyResult<Vec<_>>>()
        })
        .transpose()?;

    Ok(Some(ManualCodeSplittingOptions {
        min_share_count,
        min_size,
        max_size,
        min_module_size,
        max_module_size,
        include_dependencies_recursively,
        groups,
    }))
}

fn parse_devtools(devtools: Option<&Bound<'_, PyAny>>) -> PyResult<(bool, Option<String>)> {
    let Some(devtools) = devtools else {
        return Ok((false, None));
    };

    if devtools.is_instance_of::<PyBool>() {
        let enabled = devtools.cast::<PyBool>()?.extract::<bool>()?;
        return Ok((enabled, None));
    }

    let mapping = devtools
        .cast::<PyDict>()
        .map_err(|_| PyTypeError::new_err("Bundler.devtools must be a mapping or a boolean"))?;
    ensure_supported_mapping_fields(
        mapping,
        "Bundler.devtools",
        &["sessionId", "session_id"],
    )?;

    let session_id = get_mapping_item(mapping, &["sessionId", "session_id"])?
        .map(|value| {
            extract_string(
                &value,
                "Bundler.devtools.session_id must be a string",
            )
        })
        .transpose()?;
    Ok((true, session_id))
}

fn parse_string_fx_hash_map(
    mapping: &Bound<'_, PyDict>,
    container: &str,
    key_label: &str,
) -> PyResult<FxHashMap<String, String>> {
    let mut out = FxHashMap::default();
    for (k, v) in mapping.iter() {
        let k = extract_string(&k, &format!("{container}.{key_label} keys must be strings"))?;
        let v = extract_string(&v, &format!("{container}.{key_label} values must be strings"))?;
        out.insert(k, v);
    }
    Ok(out)
}

fn parse_output_exports(value: &Bound<'_, PyAny>, label: &str) -> PyResult<OutputExports> {
    let s = extract_string(
        value,
        &format!("{label} must be 'default', 'named', 'none', or 'auto'"),
    )?;
    match s.as_str() {
        "default" => Ok(OutputExports::Default),
        "named" => Ok(OutputExports::Named),
        "none" => Ok(OutputExports::None),
        "auto" => Ok(OutputExports::Auto),
        _ => Err(PyValueError::new_err(format!(
            "{label} must be 'default', 'named', 'none', or 'auto'"
        ))),
    }
}

fn parse_es_module_flag(value: &Bound<'_, PyAny>, label: &str) -> PyResult<EsModuleFlag> {
    if value.is_instance_of::<PyBool>() {
        return Ok(EsModuleFlag::from(value.cast::<PyBool>()?.extract::<bool>()?));
    }
    let s = extract_string(
        value,
        &format!("{label} must be a boolean or 'if-default-prop'"),
    )?;
    match s.as_str() {
        "if-default-prop" => Ok(EsModuleFlag::IfDefaultProp),
        _ => Err(PyValueError::new_err(format!(
            "{label} must be a boolean or 'if-default-prop'"
        ))),
    }
}

fn parse_strict_mode(value: &Bound<'_, PyAny>, label: &str) -> PyResult<StrictMode> {
    if value.is_instance_of::<PyBool>() {
        return Ok(StrictMode::from(value.cast::<PyBool>()?.extract::<bool>()?));
    }
    let s = extract_string(value, &format!("{label} must be a boolean or 'auto'"))?;
    StrictMode::try_from(s).map_err(PyValueError::new_err)
}

fn parse_legal_comments(value: &Bound<'_, PyAny>, label: &str) -> PyResult<LegalComments> {
    let s = extract_string(value, &format!("{label} must be 'none' or 'inline'"))?;
    match s.as_str() {
        "none" => Ok(LegalComments::None),
        "inline" => Ok(LegalComments::Inline),
        _ => Err(PyValueError::new_err(format!(
            "{label} must be 'none' or 'inline'"
        ))),
    }
}

fn parse_hash_characters(value: &Bound<'_, PyAny>, label: &str) -> PyResult<HashCharacters> {
    let s = extract_string(
        value,
        &format!("{label} must be 'base64', 'base36', or 'hex'"),
    )?;
    match s.as_str() {
        "base64" => Ok(HashCharacters::Base64),
        "base36" => Ok(HashCharacters::Base36),
        "hex" => Ok(HashCharacters::Hex),
        _ => Err(PyValueError::new_err(format!(
            "{label} must be 'base64', 'base36', or 'hex'"
        ))),
    }
}

fn parse_generated_code_mapping(
    mapping: &Bound<'_, PyDict>,
    container: &str,
) -> PyResult<GeneratedCodeOptions> {
    ensure_supported_mapping_fields(mapping, container, &["symbols", "preset"])?;
    let preset = get_mapping_item(mapping, &["preset"])?
        .map(|v| extract_string(&v, &format!("{container}.preset must be a string")))
        .transpose()?;
    if let Some(p) = &preset {
        return match p.as_str() {
            "es5" => Ok(GeneratedCodeOptions::es5()),
            "es2015" => Ok(GeneratedCodeOptions::es2015()),
            _ => Err(PyValueError::new_err(format!(
                "{container}.preset must be 'es5' or 'es2015'"
            ))),
        };
    }
    let symbols = get_mapping_item(mapping, &["symbols"])?
        .map(|v| {
            v.cast::<PyBool>()
                .map_err(|_| PyTypeError::new_err(format!("{container}.symbols must be a boolean")))?
                .extract()
        })
        .transpose()?
        .unwrap_or(true);
    Ok(GeneratedCodeOptions { symbols })
}

fn parse_comments_for_output(
    value: &Bound<'_, PyAny>,
    label: &str,
) -> PyResult<CommentsOptions> {
    if value.is_instance_of::<PyBool>() {
        let b = value.cast::<PyBool>()?.extract::<bool>()?;
        return Ok(CommentsOptions { legal: b, annotation: b, jsdoc: b });
    }
    let mapping = value
        .cast::<PyDict>()
        .map_err(|_| PyTypeError::new_err(format!("{label} must be a boolean or a mapping")))?;
    ensure_supported_mapping_fields(mapping, label, &["legal", "annotation", "jsdoc"])?;
    Ok(CommentsOptions {
        legal: get_mapping_item(mapping, &["legal"])?
            .map(|v| {
                v.cast::<PyBool>()
                    .map_err(|_| PyTypeError::new_err(format!("{label}.legal must be a boolean")))?
                    .extract()
            })
            .transpose()?
            .unwrap_or(true),
        annotation: get_mapping_item(mapping, &["annotation"])?
            .map(|v| {
                v.cast::<PyBool>()
                    .map_err(|_| {
                        PyTypeError::new_err(format!("{label}.annotation must be a boolean"))
                    })?
                    .extract()
            })
            .transpose()?
            .unwrap_or(true),
        jsdoc: get_mapping_item(mapping, &["jsdoc"])?
            .map(|v| {
                v.cast::<PyBool>()
                    .map_err(|_| PyTypeError::new_err(format!("{label}.jsdoc must be a boolean")))?
                    .extract()
            })
            .transpose()?
            .unwrap_or(true),
    })
}

fn parse_minify_for_output(value: &Bound<'_, PyAny>, label: &str) -> PyResult<RawMinifyOptions> {
    if value.is_instance_of::<PyBool>() {
        return Ok(if value.cast::<PyBool>()?.extract::<bool>()? {
            RawMinifyOptions::Bool(true)
        } else {
            RawMinifyOptions::Bool(false)
        });
    }
    let s = extract_string(
        value,
        &format!("{label} must be a boolean, 'dce-only', or 'dceOnly'"),
    )?;
    match s.as_str() {
        "dce-only" | "dceOnly" => Ok(RawMinifyOptions::DeadCodeEliminationOnly),
        _ => Err(PyValueError::new_err(format!(
            "{label} must be a boolean, 'dce-only', or 'dceOnly'"
        ))),
    }
}

fn parse_output_config(
    output: Option<&Bound<'_, PyAny>>,
    container: &str,
) -> PyResult<Option<OutputConfig>> {
    let Some(output) = output else {
        return Ok(None);
    };
    let mapping = output
        .cast::<PyDict>()
        .map_err(|_| PyTypeError::new_err(format!("{container} must be a mapping")))?;
    ensure_supported_mapping_fields(
        mapping,
        container,
        &[
            "dir",
            "file",
            "format",
            "entryFileNames",
            "entry_file_names",
            "chunkFileNames",
            "chunk_file_names",
            "assetFileNames",
            "asset_file_names",
            "sourcemap",
            "name",
            "banner",
            "postBanner",
            "post_banner",
            "footer",
            "postFooter",
            "post_footer",
            "intro",
            "outro",
            "globals",
            "paths",
            "exports",
            "esModule",
            "es_module",
            "extend",
            "externalLiveBindings",
            "external_live_bindings",
            "inlineDynamicImports",
            "inline_dynamic_imports",
            "dynamicImportInCjs",
            "dynamic_import_in_cjs",
            "hashCharacters",
            "hash_characters",
            "generatedCode",
            "generated_code",
            "sourcemapBaseUrl",
            "sourcemap_base_url",
            "sourcemapDebugIds",
            "sourcemap_debug_ids",
            "sourcemapExcludeSources",
            "sourcemap_exclude_sources",
            "strict",
            "legalComments",
            "legal_comments",
            "comments",
            "polyfillRequire",
            "polyfill_require",
            "preserveModules",
            "preserve_modules",
            "virtualDirname",
            "virtual_dirname",
            "preserveModulesRoot",
            "preserve_modules_root",
            "topLevelVar",
            "top_level_var",
            "minifyInternalExports",
            "minify_internal_exports",
            "cleanDir",
            "clean_dir",
            "strictExecutionOrder",
            "strict_execution_order",
            "minify",
            "sanitizeFileName",
            "sanitize_file_name",
        ],
    )?;

    let dir = get_mapping_item(mapping, &["dir"])?
        .map(|value| {
            extract_path_as_string(
                &value,
                &format!("{container}.dir must be a string path or os.PathLike path"),
            )
        })
        .transpose()?;
    let file = get_mapping_item(mapping, &["file"])?
        .map(|value| {
            extract_path_as_string(
                &value,
                &format!("{container}.file must be a string path or os.PathLike path"),
            )
        })
        .transpose()?;
    let format = get_mapping_item(mapping, &["format"])?
        .map(|value| {
            parse_output_format(
                &value,
                &format!(
                    "{container}.format must be one of 'es', 'esm', 'module', 'cjs', 'commonjs', 'iife', or 'umd'",
                ),
            )
        })
        .transpose()?;
    let entry_file_names = get_mapping_item(mapping, &["entryFileNames", "entry_file_names"])?
        .map(|value| {
            extract_path_as_string(
                &value,
                &format!(
                    "{container}.entry_file_names must be a string or os.PathLike path",
                ),
            )
        })
        .transpose()?;
    let chunk_file_names = get_mapping_item(mapping, &["chunkFileNames", "chunk_file_names"])?
        .map(|value| {
            extract_path_as_string(
                &value,
                &format!(
                    "{container}.chunk_file_names must be a string or os.PathLike path",
                ),
            )
        })
        .transpose()?;
    let asset_file_names = get_mapping_item(mapping, &["assetFileNames", "asset_file_names"])?
        .map(|value| {
            extract_path_as_string(
                &value,
                &format!(
                    "{container}.asset_file_names must be a string or os.PathLike path",
                ),
            )
        })
        .transpose()?;
    let sourcemap = get_mapping_item(mapping, &["sourcemap"])?
        .map(|value| {
            parse_sourcemap_setting(
                &value,
                &format!(
                    "{container}.sourcemap must be a boolean or one of 'file', 'inline', or 'hidden'",
                ),
            )
        })
        .transpose()?;
    let name = get_mapping_item(mapping, &["name"])?
        .map(|value| extract_string(&value, &format!("{container}.name must be a string")))
        .transpose()?;

    let banner = get_mapping_item(mapping, &["banner"])?
        .map(|v| extract_string(&v, &format!("{container}.banner must be a string")))
        .transpose()?;
    let post_banner = get_mapping_item(mapping, &["postBanner", "post_banner"])?
        .map(|v| extract_string(&v, &format!("{container}.post_banner must be a string")))
        .transpose()?;
    let footer = get_mapping_item(mapping, &["footer"])?
        .map(|v| extract_string(&v, &format!("{container}.footer must be a string")))
        .transpose()?;
    let post_footer = get_mapping_item(mapping, &["postFooter", "post_footer"])?
        .map(|v| extract_string(&v, &format!("{container}.post_footer must be a string")))
        .transpose()?;
    let intro = get_mapping_item(mapping, &["intro"])?
        .map(|v| extract_string(&v, &format!("{container}.intro must be a string")))
        .transpose()?;
    let outro = get_mapping_item(mapping, &["outro"])?
        .map(|v| extract_string(&v, &format!("{container}.outro must be a string")))
        .transpose()?;

    let globals = get_mapping_item(mapping, &["globals"])?
        .map(|v| {
            let m = v.cast::<PyDict>().map_err(|_| {
                PyTypeError::new_err(format!("{container}.globals must be a string-keyed mapping"))
            })?;
            parse_string_fx_hash_map(m, container, "globals")
        })
        .transpose()?;

    let paths = get_mapping_item(mapping, &["paths"])?
        .map(|v| {
            let m = v.cast::<PyDict>().map_err(|_| {
                PyTypeError::new_err(format!("{container}.paths must be a string-keyed mapping"))
            })?;
            parse_string_fx_hash_map(m, container, "paths")
        })
        .transpose()?;

    let exports = get_mapping_item(mapping, &["exports"])?
        .map(|v| parse_output_exports(&v, &format!("{container}.exports")))
        .transpose()?;

    let es_module = get_mapping_item(mapping, &["esModule", "es_module"])?
        .map(|v| parse_es_module_flag(&v, &format!("{container}.es_module")))
        .transpose()?;

    let extend = get_mapping_item(mapping, &["extend"])?
        .map(|v| {
            v.cast::<PyBool>()
                .map_err(|_| PyTypeError::new_err(format!("{container}.extend must be a boolean")))?
                .extract()
        })
        .transpose()?;

    let external_live_bindings =
        get_mapping_item(mapping, &["externalLiveBindings", "external_live_bindings"])?
            .map(|v| {
                v.cast::<PyBool>()
                    .map_err(|_| {
                        PyTypeError::new_err(format!(
                            "{container}.external_live_bindings must be a boolean"
                        ))
                    })?
                    .extract()
            })
            .transpose()?;

    let inline_dynamic_imports =
        get_mapping_item(mapping, &["inlineDynamicImports", "inline_dynamic_imports"])?
            .map(|v| {
                v.cast::<PyBool>()
                    .map_err(|_| {
                        PyTypeError::new_err(format!(
                            "{container}.inline_dynamic_imports must be a boolean"
                        ))
                    })?
                    .extract()
            })
            .transpose()?;

    let dynamic_import_in_cjs =
        get_mapping_item(mapping, &["dynamicImportInCjs", "dynamic_import_in_cjs"])?
            .map(|v| {
                v.cast::<PyBool>()
                    .map_err(|_| {
                        PyTypeError::new_err(format!(
                            "{container}.dynamic_import_in_cjs must be a boolean"
                        ))
                    })?
                    .extract()
            })
            .transpose()?;

    let hash_characters = get_mapping_item(mapping, &["hashCharacters", "hash_characters"])?
        .map(|v| parse_hash_characters(&v, &format!("{container}.hash_characters")))
        .transpose()?;

    let generated_code = get_mapping_item(mapping, &["generatedCode", "generated_code"])?
        .map(|v| {
            let m = v.cast::<PyDict>().map_err(|_| {
                PyTypeError::new_err(format!("{container}.generated_code must be a mapping"))
            })?;
            parse_generated_code_mapping(m, &format!("{container}.generated_code"))
        })
        .transpose()?;

    let sourcemap_base_url =
        get_mapping_item(mapping, &["sourcemapBaseUrl", "sourcemap_base_url"])?
            .map(|v| extract_string(&v, &format!("{container}.sourcemap_base_url must be a string")))
            .transpose()?;

    let sourcemap_debug_ids = get_mapping_item(mapping, &["sourcemapDebugIds", "sourcemap_debug_ids"])?
        .map(|v| {
            v.cast::<PyBool>()
                .map_err(|_| {
                    PyTypeError::new_err(format!(
                        "{container}.sourcemap_debug_ids must be a boolean"
                    ))
                })?
                .extract()
        })
        .transpose()?;

    let sourcemap_exclude_sources = get_mapping_item(
        mapping,
        &["sourcemapExcludeSources", "sourcemap_exclude_sources"],
    )?
    .map(|v| {
        v.cast::<PyBool>()
            .map_err(|_| {
                PyTypeError::new_err(format!(
                    "{container}.sourcemap_exclude_sources must be a boolean"
                ))
            })?
            .extract()
    })
    .transpose()?;

    let strict = get_mapping_item(mapping, &["strict"])?
        .map(|v| parse_strict_mode(&v, &format!("{container}.strict")))
        .transpose()?;

    let legal_comments = get_mapping_item(mapping, &["legalComments", "legal_comments"])?
        .map(|v| parse_legal_comments(&v, &format!("{container}.legal_comments")))
        .transpose()?;

    let comments = get_mapping_item(mapping, &["comments"])?
        .map(|v| parse_comments_for_output(&v, &format!("{container}.comments")))
        .transpose()?;

    let polyfill_require = get_mapping_item(mapping, &["polyfillRequire", "polyfill_require"])?
        .map(|v| {
            v.cast::<PyBool>()
                .map_err(|_| {
                    PyTypeError::new_err(format!("{container}.polyfill_require must be a boolean"))
                })?
                .extract()
        })
        .transpose()?;

    let preserve_modules = get_mapping_item(mapping, &["preserveModules", "preserve_modules"])?
        .map(|v| {
            v.cast::<PyBool>()
                .map_err(|_| {
                    PyTypeError::new_err(format!("{container}.preserve_modules must be a boolean"))
                })?
                .extract()
        })
        .transpose()?;

    let virtual_dirname = get_mapping_item(mapping, &["virtualDirname", "virtual_dirname"])?
        .map(|v| extract_string(&v, &format!("{container}.virtual_dirname must be a string")))
        .transpose()?;

    let preserve_modules_root =
        get_mapping_item(mapping, &["preserveModulesRoot", "preserve_modules_root"])?
            .map(|v| {
                extract_string(&v, &format!("{container}.preserve_modules_root must be a string"))
            })
            .transpose()?;

    let top_level_var = get_mapping_item(mapping, &["topLevelVar", "top_level_var"])?
        .map(|v| {
            v.cast::<PyBool>()
                .map_err(|_| {
                    PyTypeError::new_err(format!("{container}.top_level_var must be a boolean"))
                })?
                .extract()
        })
        .transpose()?;

    let minify_internal_exports = get_mapping_item(
        mapping,
        &["minifyInternalExports", "minify_internal_exports"],
    )?
    .map(|v| {
        v.cast::<PyBool>()
            .map_err(|_| {
                PyTypeError::new_err(format!(
                    "{container}.minify_internal_exports must be a boolean"
                ))
            })?
            .extract()
    })
    .transpose()?;

    let clean_dir = get_mapping_item(mapping, &["cleanDir", "clean_dir"])?
        .map(|v| {
            v.cast::<PyBool>()
                .map_err(|_| PyTypeError::new_err(format!("{container}.clean_dir must be a boolean")))?
                .extract()
        })
        .transpose()?;

    let strict_execution_order = get_mapping_item(
        mapping,
        &["strictExecutionOrder", "strict_execution_order"],
    )?
    .map(|v| {
        v.cast::<PyBool>()
            .map_err(|_| {
                PyTypeError::new_err(format!(
                    "{container}.strict_execution_order must be a boolean"
                ))
            })?
            .extract()
    })
    .transpose()?;

    let minify = get_mapping_item(mapping, &["minify"])?
        .map(|v| parse_minify_for_output(&v, &format!("{container}.minify")))
        .transpose()?;

    let sanitize_file_name = get_mapping_item(mapping, &["sanitizeFileName", "sanitize_file_name"])?
        .map(|v| {
            if v.is_instance_of::<PyBool>() {
                Ok(SanitizeFilename::from(v.cast::<PyBool>()?.extract::<bool>()?))
            } else {
                Err(PyTypeError::new_err(format!(
                    "{container}.sanitize_file_name must be a boolean"
                )))
            }
        })
        .transpose()?;

    Ok(Some(OutputConfig {
        dir,
        file,
        format,
        entry_file_names,
        chunk_file_names,
        asset_file_names,
        sourcemap,
        name,
        banner,
        post_banner,
        footer,
        post_footer,
        intro,
        outro,
        globals,
        paths,
        exports,
        es_module,
        extend,
        external_live_bindings,
        inline_dynamic_imports,
        dynamic_import_in_cjs,
        hash_characters,
        generated_code,
        sourcemap_base_url,
        sourcemap_debug_ids,
        sourcemap_exclude_sources,
        strict,
        legal_comments,
        comments,
        polyfill_require,
        preserve_modules,
        virtual_dirname,
        preserve_modules_root,
        top_level_var,
        minify_internal_exports,
        clean_dir,
        strict_execution_order,
        minify,
        sanitize_file_name,
    }))
}

impl BundlerConfigState {
    #[allow(clippy::too_many_arguments)]
    fn from_python(
        py: Python<'_>,
        input: &Bound<'_, PyAny>,
        cwd: Option<&Bound<'_, PyAny>>,
        resolve: Option<&Bound<'_, PyAny>>,
        devtools: Option<&Bound<'_, PyAny>>,
        output: Option<&Bound<'_, PyAny>>,
        plugins: Option<&Bound<'_, PyAny>>,
        watch: Option<&Bound<'_, PyAny>>,
        platform: Option<&Bound<'_, PyAny>>,
        context: Option<&Bound<'_, PyAny>>,
        tsconfig: Option<&Bound<'_, PyAny>>,
        shim_missing_exports: Option<&Bound<'_, PyAny>>,
        keep_names: Option<&Bound<'_, PyAny>>,
        profiler_names: Option<&Bound<'_, PyAny>>,
        define: Option<&Bound<'_, PyAny>>,
        drop_labels: Option<&Bound<'_, PyAny>>,
        inject: Option<&Bound<'_, PyAny>>,
        external: Option<&Bound<'_, PyAny>>,
        treeshake: Option<&Bound<'_, PyAny>>,
        manual_code_splitting: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        if plugins.is_some() {
            return Err(unsupported_feature_error("Bundler.plugins"));
        }

        if let Some(watch) = watch {
            let watch_is_disabled =
                watch.is_instance_of::<PyBool>() && !watch.cast::<PyBool>()?.extract::<bool>()?;
            if !watch_is_disabled {
                return Err(unsupported_feature_error("Bundler.watch"));
            }
        }

        let input = parse_input(input)?;
        let resolve = parse_resolve_options(resolve)?;
        let (devtools_enabled, devtools_session_id) = parse_devtools(devtools)?;
        let default_output = parse_output_config(output, "Bundler.output")?;
        let platform = parse_platform(platform)?;
        let context = context
            .map(|v| extract_string(v, "Bundler.context must be a string"))
            .transpose()?;
        let tsconfig = parse_tsconfig(tsconfig)?;
        let shim_missing_exports = shim_missing_exports
            .map(|v| {
                v.cast::<PyBool>()
                    .map_err(|_| PyTypeError::new_err("Bundler.shim_missing_exports must be a boolean"))?
                    .extract()
            })
            .transpose()?;
        let keep_names = keep_names
            .map(|v| {
                v.cast::<PyBool>()
                    .map_err(|_| PyTypeError::new_err("Bundler.keep_names must be a boolean"))?
                    .extract()
            })
            .transpose()?;
        let profiler_names = profiler_names
            .map(|v| {
                v.cast::<PyBool>()
                    .map_err(|_| PyTypeError::new_err("Bundler.profiler_names must be a boolean"))?
                    .extract()
            })
            .transpose()?;
        let define = parse_define(define)?;
        let drop_labels = drop_labels
            .map(|v| {
                extract_string_sequence(
                    v,
                    "Bundler.drop_labels must be a sequence of strings",
                )
            })
            .transpose()?;
        let inject = parse_inject(inject)?;
        let external = parse_external(py, external)?;
        let treeshake = parse_treeshake(treeshake)?;
        let manual_code_splitting = parse_manual_code_splitting(manual_code_splitting)?;

        Ok(Self {
            input,
            cwd: parse_optional_cwd(cwd)?,
            resolve,
            devtools_enabled,
            devtools_session_id,
            default_output,
            platform,
            context,
            tsconfig,
            shim_missing_exports,
            keep_names,
            profiler_names,
            define,
            drop_labels,
            inject,
            external,
            treeshake,
            manual_code_splitting,
        })
    }
}

impl OutputConfig {
    fn merge(base: Option<&Self>, override_config: Option<Self>) -> Option<Self> {
        match (base.cloned(), override_config) {
            (None, None) => None,
            (Some(base), None) => Some(base),
            (None, Some(override_config)) => Some(override_config),
            (Some(mut base), Some(override_config)) => {
                macro_rules! merge_opt {
                    ($field:ident) => {
                        if override_config.$field.is_some() {
                            base.$field = override_config.$field;
                        }
                    };
                }
                merge_opt!(dir);
                merge_opt!(file);
                merge_opt!(format);
                merge_opt!(entry_file_names);
                merge_opt!(chunk_file_names);
                merge_opt!(asset_file_names);
                merge_opt!(sourcemap);
                merge_opt!(name);
                merge_opt!(banner);
                merge_opt!(post_banner);
                merge_opt!(footer);
                merge_opt!(post_footer);
                merge_opt!(intro);
                merge_opt!(outro);
                merge_opt!(globals);
                merge_opt!(paths);
                merge_opt!(exports);
                merge_opt!(es_module);
                merge_opt!(extend);
                merge_opt!(external_live_bindings);
                merge_opt!(inline_dynamic_imports);
                merge_opt!(dynamic_import_in_cjs);
                merge_opt!(hash_characters);
                merge_opt!(generated_code);
                merge_opt!(sourcemap_base_url);
                merge_opt!(sourcemap_debug_ids);
                merge_opt!(sourcemap_exclude_sources);
                merge_opt!(strict);
                merge_opt!(legal_comments);
                merge_opt!(comments);
                merge_opt!(polyfill_require);
                merge_opt!(preserve_modules);
                merge_opt!(virtual_dirname);
                merge_opt!(preserve_modules_root);
                merge_opt!(top_level_var);
                merge_opt!(minify_internal_exports);
                merge_opt!(clean_dir);
                merge_opt!(strict_execution_order);
                merge_opt!(minify);
                merge_opt!(sanitize_file_name);
                Some(base)
            }
        }
    }

    fn apply_to_bundler_options(&self, options: &mut BundlerOptions) {
        if let Some(dir) = &self.dir {
            options.dir = Some(dir.clone());
        }
        if let Some(file) = &self.file {
            options.file = Some(file.clone());
        }
        if let Some(format) = self.format {
            options.format = Some(format);
        }
        if let Some(entry_file_names) = &self.entry_file_names {
            options.entry_filenames = Some(ChunkFilenamesOutputOption::from(
                entry_file_names.clone(),
            ));
        }
        if let Some(chunk_file_names) = &self.chunk_file_names {
            options.chunk_filenames = Some(ChunkFilenamesOutputOption::from(
                chunk_file_names.clone(),
            ));
        }
        if let Some(asset_file_names) = &self.asset_file_names {
            options.asset_filenames = Some(AssetFilenamesOutputOption::from(
                asset_file_names.clone(),
            ));
        }
        if let Some(sourcemap) = &self.sourcemap {
            options.sourcemap = match sourcemap {
                SourcemapSetting::Disabled => None,
                SourcemapSetting::Enabled(kind) => Some(*kind),
            };
        }
        if let Some(name) = &self.name {
            options.name = Some(name.clone());
        }
        if let Some(banner) = &self.banner {
            options.banner = Some(AddonOutputOption::String(Some(banner.clone())));
        }
        if let Some(post_banner) = &self.post_banner {
            options.post_banner = Some(AddonOutputOption::String(Some(post_banner.clone())));
        }
        if let Some(footer) = &self.footer {
            options.footer = Some(AddonOutputOption::String(Some(footer.clone())));
        }
        if let Some(post_footer) = &self.post_footer {
            options.post_footer = Some(AddonOutputOption::String(Some(post_footer.clone())));
        }
        if let Some(intro) = &self.intro {
            options.intro = Some(AddonOutputOption::String(Some(intro.clone())));
        }
        if let Some(outro) = &self.outro {
            options.outro = Some(AddonOutputOption::String(Some(outro.clone())));
        }
        if let Some(globals) = &self.globals {
            options.globals = Some(GlobalsOutputOption::from(globals.clone()));
        }
        if let Some(paths) = &self.paths {
            options.paths = Some(PathsOutputOption::from(paths.clone()));
        }
        if let Some(exports) = self.exports {
            options.exports = Some(exports);
        }
        if let Some(es_module) = self.es_module {
            options.es_module = Some(es_module);
        }
        if let Some(extend) = self.extend {
            options.extend = Some(extend);
        }
        if let Some(external_live_bindings) = self.external_live_bindings {
            options.external_live_bindings = Some(external_live_bindings);
        }
        if let Some(inline_dynamic_imports) = self.inline_dynamic_imports {
            options.code_splitting = Some(CodeSplittingMode::Bool(!inline_dynamic_imports));
        }
        if let Some(dynamic_import_in_cjs) = self.dynamic_import_in_cjs {
            options.dynamic_import_in_cjs = Some(dynamic_import_in_cjs);
        }
        if let Some(hash_characters) = self.hash_characters {
            options.hash_characters = Some(hash_characters);
        }
        if let Some(generated_code) = self.generated_code {
            options.generated_code = Some(generated_code);
        }
        if let Some(sourcemap_base_url) = &self.sourcemap_base_url {
            options.sourcemap_base_url = Some(sourcemap_base_url.clone());
        }
        if let Some(sourcemap_debug_ids) = self.sourcemap_debug_ids {
            options.sourcemap_debug_ids = Some(sourcemap_debug_ids);
        }
        if let Some(sourcemap_exclude_sources) = self.sourcemap_exclude_sources {
            options.sourcemap_exclude_sources = Some(sourcemap_exclude_sources);
        }
        if let Some(strict) = self.strict {
            options.strict = Some(strict);
        }
        if let Some(legal_comments) = self.legal_comments {
            options.legal_comments = Some(legal_comments);
        }
        if let Some(comments) = self.comments {
            options.comments = Some(comments);
        }
        if let Some(polyfill_require) = self.polyfill_require {
            options.polyfill_require = Some(polyfill_require);
        }
        if let Some(preserve_modules) = self.preserve_modules {
            options.preserve_modules = Some(preserve_modules);
        }
        if let Some(virtual_dirname) = &self.virtual_dirname {
            options.virtual_dirname = Some(virtual_dirname.clone());
        }
        if let Some(preserve_modules_root) = &self.preserve_modules_root {
            options.preserve_modules_root = Some(preserve_modules_root.clone());
        }
        if let Some(top_level_var) = self.top_level_var {
            options.top_level_var = Some(top_level_var);
        }
        if let Some(minify_internal_exports) = self.minify_internal_exports {
            options.minify_internal_exports = Some(minify_internal_exports);
        }
        if let Some(clean_dir) = self.clean_dir {
            options.clean_dir = Some(clean_dir);
        }
        if let Some(strict_execution_order) = self.strict_execution_order {
            options.strict_execution_order = Some(strict_execution_order);
        }
        if let Some(minify) = &self.minify {
            options.minify = Some(minify.clone());
        }
        if let Some(sanitize_file_name) = &self.sanitize_file_name {
            options.sanitize_filename = Some(sanitize_file_name.clone());
        }
    }
}

impl OutputChunk {
    fn from_chunk(chunk: &rolldown_common::OutputChunk) -> Self {
        Self {
            name: chunk.name.to_string(),
            file_name: chunk.filename.to_string(),
            code: chunk.code.clone(),
            is_entry: chunk.is_entry,
            is_dynamic_entry: chunk.is_dynamic_entry,
            facade_module_id: chunk.facade_module_id.as_ref().map(ToString::to_string),
            module_ids: chunk.module_ids.iter().map(ToString::to_string).collect(),
            exports: chunk.exports.iter().map(ToString::to_string).collect(),
            imports: chunk.imports.iter().map(ToString::to_string).collect(),
            dynamic_imports: chunk.dynamic_imports.iter().map(ToString::to_string).collect(),
            sourcemap: chunk.map.as_ref().map(|map| map.to_json_string()),
            sourcemap_file_name: chunk.sourcemap_filename.clone(),
            preliminary_file_name: chunk.preliminary_filename.clone(),
        }
    }
}

impl OutputAsset {
    fn from_asset(asset: &rolldown_common::OutputAsset) -> Self {
        let source = match &asset.source {
            rolldown_common::StrOrBytes::Str(text) => OutputAssetSource::String(text.clone()),
            rolldown_common::StrOrBytes::Bytes(bytes) => OutputAssetSource::Bytes(bytes.clone()),
        };

        Self {
            file_name: asset.filename.to_string(),
            names: asset.names.clone(),
            original_file_names: asset.original_file_names.clone(),
            source,
        }
    }
}

impl BundlerOutput {
    fn from_bundle_output(output: BundleOutput) -> Self {
        let mut chunks = Vec::new();
        let mut assets = Vec::new();
        for item in output.assets {
            match item {
                rolldown_common::Output::Chunk(chunk) => {
                    chunks.push(OutputChunk::from_chunk(chunk.as_ref()));
                }
                rolldown_common::Output::Asset(asset) => {
                    assets.push(OutputAsset::from_asset(asset.as_ref()));
                }
            }
        }

        let warnings = output
            .warnings
            .into_iter()
            .map(|warning| warning.to_diagnostic().to_string())
            .collect();

        Self {
            chunks,
            assets,
            warnings,
        }
    }
}

fn create_bundler_options(
    config: &BundlerConfigState,
    output_override: Option<OutputConfig>,
    write: Option<bool>,
) -> PyResult<(BundlerOptions, bool)> {
    let cwd = match &config.cwd {
        Some(cwd) => cwd.clone(),
        None => std::env::current_dir()
            .map_err(|err| PyRuntimeError::new_err(format!("failed to read current working directory: {err}")))?,
    };

    let mut options = BundlerOptions {
        input: Some(config.input.clone()),
        cwd: Some(cwd.clone()),
        ..Default::default()
    };

    if let Some(resolve) = &config.resolve {
        options.resolve = Some(resolve.clone());
    }

    if let Some(platform) = config.platform {
        options.platform = Some(platform);
    }
    if let Some(context) = &config.context {
        options.context = Some(context.clone());
    }
    if let Some(tsconfig) = &config.tsconfig {
        options.tsconfig = Some(tsconfig.clone().with_base(&cwd));
    }
    if let Some(shim_missing_exports) = config.shim_missing_exports {
        options.shim_missing_exports = Some(shim_missing_exports);
    }
    if let Some(keep_names) = config.keep_names {
        options.keep_names = Some(keep_names);
    }
    if let Some(profiler_names) = config.profiler_names {
        options.profiler_names = Some(profiler_names);
    }
    if let Some(define) = &config.define {
        options.define = Some(define.clone());
    }
    if let Some(drop_labels) = &config.drop_labels {
        options.drop_labels = Some(drop_labels.clone());
    }
    if let Some(inject) = &config.inject {
        options.inject = Some(inject.clone());
    }
    if let Some(external) = &config.external {
        options.external = Some(external.clone());
    }
    if let Some(treeshake) = &config.treeshake {
        options.treeshake = treeshake.clone();
    }
    if let Some(manual_code_splitting) = &config.manual_code_splitting {
        options.manual_code_splitting = Some(manual_code_splitting.clone());
    }

    if config.devtools_enabled {
        options.devtools = Some(DevtoolsOptions {
            session_id: config.devtools_session_id.clone(),
        });
    }

    let effective_output = OutputConfig::merge(config.default_output.as_ref(), output_override);
    if let Some(output) = &effective_output {
        output.apply_to_bundler_options(&mut options);
    }

    Ok((options, write.unwrap_or(effective_output.is_some())))
}

async fn build_once(
    config: Arc<BundlerConfigState>,
    output_override: Option<OutputConfig>,
    write: Option<bool>,
) -> PyResult<BundlerOutput> {
    let (options, should_write) = create_bundler_options(config.as_ref(), output_override, write)?;
    let mut bundler = RolldownBundler::new(options).map_err(|errs| {
        PyRuntimeError::new_err(format!(
            "failed to initialize Bundler: {}",
            errs.iter()
                .map(|diagnostic| diagnostic.to_diagnostic().to_string())
                .collect::<Vec<_>>()
                .join("\n"),
        ))
    })?;

    let bundle_output = if should_write {
        bundler.write().await
    } else {
        bundler.generate().await
    }
    .map_err(|errs| {
        PyRuntimeError::new_err(format!(
            "bundling failed: {}",
            errs.iter()
                .map(|diagnostic| diagnostic.to_diagnostic().to_string())
                .collect::<Vec<_>>()
                .join("\n"),
        ))
    })?;

    bundler.close().await.map_err(|errs| {
        PyRuntimeError::new_err(format!(
            "failed to close Bundler: {}",
            errs.iter()
                .map(|diagnostic| diagnostic.to_diagnostic().to_string())
                .collect::<Vec<_>>()
                .join("\n"),
        ))
    })?;

    Ok(BundlerOutput::from_bundle_output(bundle_output))
}

fn build_once_blocking(
    config: Arc<BundlerConfigState>,
    output_override: Option<OutputConfig>,
    write: Option<bool>,
) -> PyResult<BundlerOutput> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|err| PyRuntimeError::new_err(format!("failed to create tokio runtime: {err}")))?;

    runtime.block_on(build_once(config, output_override, write))
}

impl BundlerContext {
    fn ensure_inactive(&self) -> PyResult<()> {
        if self.active {
            return Err(PyRuntimeError::new_err(BUNDLER_CONTEXT_ALREADY_ACTIVE));
        }

        Ok(())
    }

    fn ensure_active(&self) -> PyResult<()> {
        if !self.active {
            return Err(PyRuntimeError::new_err(BUNDLER_CONTEXT_NOT_ACTIVE));
        }

        Ok(())
    }

    fn enter(&mut self) -> PyResult<()> {
        self.ensure_inactive()?;
        self.active = true;
        Ok(())
    }
}

impl AsyncBundlerContext {
    fn ensure_inactive(&self) -> PyResult<()> {
        if self.active {
            return Err(PyRuntimeError::new_err(BUNDLER_CONTEXT_ALREADY_ACTIVE));
        }

        Ok(())
    }

    fn ensure_active(&self) -> PyResult<()> {
        if !self.active {
            return Err(PyRuntimeError::new_err(BUNDLER_CONTEXT_NOT_ACTIVE));
        }

        Ok(())
    }

    fn enter(&mut self) -> PyResult<()> {
        self.ensure_inactive()?;
        self.active = true;
        Ok(())
    }
}

#[pymethods]
impl Bundler {
    #[new]
    #[pyo3(signature = (
        *,
        input,
        cwd = None,
        resolve = None,
        devtools = None,
        output = None,
        plugins = None,
        watch = None,
        platform = None,
        context = None,
        tsconfig = None,
        shim_missing_exports = None,
        keep_names = None,
        profiler_names = None,
        define = None,
        drop_labels = None,
        inject = None,
        external = None,
        treeshake = None,
        manual_code_splitting = None,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        py: Python<'_>,
        input: &Bound<'_, PyAny>,
        cwd: Option<Py<PyAny>>,
        resolve: Option<Py<PyAny>>,
        devtools: Option<Py<PyAny>>,
        output: Option<Py<PyAny>>,
        plugins: Option<Py<PyAny>>,
        watch: Option<Py<PyAny>>,
        platform: Option<Py<PyAny>>,
        context: Option<Py<PyAny>>,
        tsconfig: Option<Py<PyAny>>,
        shim_missing_exports: Option<Py<PyAny>>,
        keep_names: Option<Py<PyAny>>,
        profiler_names: Option<Py<PyAny>>,
        define: Option<Py<PyAny>>,
        drop_labels: Option<Py<PyAny>>,
        inject: Option<Py<PyAny>>,
        external: Option<Py<PyAny>>,
        treeshake: Option<Py<PyAny>>,
        manual_code_splitting: Option<Py<PyAny>>,
    ) -> PyResult<Self> {
        let config = BundlerConfigState::from_python(
            py,
            input,
            cwd.as_ref().map(|value| value.bind(py)),
            resolve.as_ref().map(|value| value.bind(py)),
            devtools.as_ref().map(|value| value.bind(py)),
            output.as_ref().map(|value| value.bind(py)),
            plugins.as_ref().map(|value| value.bind(py)),
            watch.as_ref().map(|value| value.bind(py)),
            platform.as_ref().map(|value| value.bind(py)),
            context.as_ref().map(|value| value.bind(py)),
            tsconfig.as_ref().map(|value| value.bind(py)),
            shim_missing_exports.as_ref().map(|value| value.bind(py)),
            keep_names.as_ref().map(|value| value.bind(py)),
            profiler_names.as_ref().map(|value| value.bind(py)),
            define.as_ref().map(|value| value.bind(py)),
            drop_labels.as_ref().map(|value| value.bind(py)),
            inject.as_ref().map(|value| value.bind(py)),
            external.as_ref().map(|value| value.bind(py)),
            treeshake.as_ref().map(|value| value.bind(py)),
            manual_code_splitting.as_ref().map(|value| value.bind(py)),
        )?;

        Ok(Self {
            config: Arc::new(config),
        })
    }

    fn __call__(slf: PyRef<'_, Self>, py: Python<'_>) -> PyResult<Py<BundlerContext>> {
        Py::new(
            py,
            BundlerContext {
                config: Arc::clone(&slf.config),
                active: false,
            },
        )
    }
}

#[pymethods]
impl BundlerContext {
    #[new]
    fn new(bundler: PyRef<'_, Bundler>) -> Self {
        Self {
            config: Arc::clone(&bundler.config),
            active: false,
        }
    }

    fn _ensure_inactive(&self) -> PyResult<()> {
        self.ensure_inactive()
    }

    fn __enter__(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<Self>> {
        slf.borrow_mut(py).enter()?;
        Ok(slf)
    }

    fn __exit__(
        &mut self,
        _exc_type: &Bound<'_, PyAny>,
        _exc_value: &Bound<'_, PyAny>,
        _traceback: &Bound<'_, PyAny>,
    ) {
        self.active = false;
    }

    #[pyo3(signature = (output = None, *, write = None))]
    fn __call__<'py>(
        &self,
        py: Python<'py>,
        output: Option<Py<PyAny>>,
        write: Option<bool>,
    ) -> PyResult<Bound<'py, PyAny>> {
        self.ensure_active()?;
        let output_override = output
            .as_ref()
            .map(|value| parse_output_config(Some(value.bind(py)), "BundlerContext.output"))
            .transpose()?
            .flatten();
        let output = build_once_blocking(Arc::clone(&self.config), output_override, write)?;
        Ok(Py::new(py, output)?.into_bound(py).into_any())
    }
}

#[pymethods]
impl AsyncBundlerContext {
    #[new]
    fn new(bundler: PyRef<'_, Bundler>) -> Self {
        Self {
            config: Arc::clone(&bundler.config),
            active: false,
        }
    }

    fn __aenter__<'py>(slf: Py<Self>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        slf.borrow_mut(py).enter()?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move { Ok(slf) })
    }

    fn __aexit__<'py>(
        &mut self,
        py: Python<'py>,
        _exc_type: &Bound<'_, PyAny>,
        _exc_value: &Bound<'_, PyAny>,
        _traceback: &Bound<'_, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        self.active = false;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            Python::attach(|py| Ok(py.None()))
        })
    }

    #[pyo3(signature = (output = None, *, write = None))]
    fn __call__<'py>(
        &self,
        py: Python<'py>,
        output: Option<Py<PyAny>>,
        write: Option<bool>,
    ) -> PyResult<Bound<'py, PyAny>> {
        self.ensure_active()?;
        let output_override = output
            .as_ref()
            .map(|value| parse_output_config(Some(value.bind(py)), "BundlerContext.output"))
            .transpose()?
            .flatten();
        let config = Arc::clone(&self.config);

        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let output = build_once(config, output_override, write).await?;
            Python::attach(|py| Ok(Py::new(py, output)?.into_bound(py).into_any().unbind()))
        })
    }
}

#[pymethods]
impl OutputChunk {
    #[getter]
    fn name(&self) -> &str {
        &self.name
    }

    #[getter]
    fn file_name(&self) -> &str {
        &self.file_name
    }

    #[getter]
    fn code(&self) -> &str {
        &self.code
    }

    #[getter]
    fn is_entry(&self) -> bool {
        self.is_entry
    }

    #[getter]
    fn is_dynamic_entry(&self) -> bool {
        self.is_dynamic_entry
    }

    #[getter]
    fn facade_module_id(&self) -> Option<&str> {
        self.facade_module_id.as_deref()
    }

    #[getter]
    fn module_ids(&self) -> Vec<String> {
        self.module_ids.clone()
    }

    #[getter]
    fn exports(&self) -> Vec<String> {
        self.exports.clone()
    }

    #[getter]
    fn imports(&self) -> Vec<String> {
        self.imports.clone()
    }

    #[getter]
    fn dynamic_imports(&self) -> Vec<String> {
        self.dynamic_imports.clone()
    }

    #[getter]
    fn sourcemap(&self) -> Option<&str> {
        self.sourcemap.as_deref()
    }

    #[getter]
    fn sourcemap_file_name(&self) -> Option<&str> {
        self.sourcemap_file_name.as_deref()
    }

    #[getter]
    fn preliminary_file_name(&self) -> &str {
        &self.preliminary_file_name
    }

    fn __repr__(&self) -> String {
        format!(
            "OutputChunk(name={:?}, file_name={:?}, is_entry={}, is_dynamic_entry={})",
            self.name, self.file_name, self.is_entry, self.is_dynamic_entry,
        )
    }
}

#[pymethods]
impl OutputAsset {
    #[getter]
    fn file_name(&self) -> &str {
        &self.file_name
    }

    #[getter]
    fn names(&self) -> Vec<String> {
        self.names.clone()
    }

    #[getter]
    fn original_file_names(&self) -> Vec<String> {
        self.original_file_names.clone()
    }

    #[getter]
    fn source(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        match &self.source {
            OutputAssetSource::String(text) => Ok(text.clone().into_pyobject(py)?.into_any().unbind()),
            OutputAssetSource::Bytes(bytes) => Ok(PyBytes::new(py, bytes).into_any().unbind()),
        }
    }

    fn __repr__(&self) -> String {
        format!("OutputAsset(file_name={:?})", self.file_name)
    }
}

#[pymethods]
impl BundlerOutput {
    #[getter]
    fn chunks(&self, py: Python<'_>) -> PyResult<Vec<Py<OutputChunk>>> {
        self.chunks
            .iter()
            .cloned()
            .map(|chunk| Py::new(py, chunk))
            .collect()
    }

    #[getter]
    fn assets(&self, py: Python<'_>) -> PyResult<Vec<Py<OutputAsset>>> {
        self.assets
            .iter()
            .cloned()
            .map(|asset| Py::new(py, asset))
            .collect()
    }

    #[getter]
    fn warnings(&self) -> Vec<String> {
        self.warnings.clone()
    }

    fn __repr__(&self) -> String {
        format!(
            "BundlerOutput(chunks={}, assets={}, warnings={})",
            self.chunks.len(),
            self.assets.len(),
            self.warnings.len(),
        )
    }
}

#[pymodule]
mod _core {
    #[pymodule_export]
    use super::{
        AsyncBundlerContext, Bundler, BundlerContext, BundlerOutput, OutputAsset, OutputChunk,
    };
}
