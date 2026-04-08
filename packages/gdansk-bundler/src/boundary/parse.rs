use std::path::PathBuf;

use pyo3::{
    exceptions::{PyRuntimeError, PyTypeError, PyValueError},
    prelude::*,
    types::{PyBool, PyDict, PyList, PyString, PyTuple},
};
use rolldown::{
    CommentsOptions, EsModuleFlag, GeneratedCodeOptions, HashCharacters, InjectImport,
    InnerOptions, InputItem, IsExternal, LegalComments, ManualCodeSplittingOptions, MatchGroup,
    MatchGroupName, MatchGroupTest, ModuleSideEffects, OutputExports, OutputFormat, Platform,
    PropertyReadSideEffects, PropertyWriteSideEffects, RawMinifyOptions, ResolveOptions,
    SanitizeFilename, SourceMapType, StrictMode, TreeshakeOptions, TsConfig,
};
use rolldown_utils::{indexmap::FxIndexMap, pattern_filter::StringOrRegex};
use rustc_hash::{FxHashMap, FxHashSet};

use crate::{OutputConfig, SourcemapSetting, unsupported_feature_error};

pub(crate) fn extract_string(value: &Bound<'_, PyAny>, message: &str) -> PyResult<String> {
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

pub(crate) fn parse_optional_cwd(value: Option<&Bound<'_, PyAny>>) -> PyResult<Option<PathBuf>> {
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

pub(crate) fn extract_string_sequence(
    value: &Bound<'_, PyAny>,
    message: &str,
) -> PyResult<Vec<String>> {
    if let Ok(list) = value.cast::<PyList>() {
        return list
            .iter()
            .map(|item| extract_string(&item, message))
            .collect();
    }

    if let Ok(tuple) = value.cast::<PyTuple>() {
        return tuple
            .iter()
            .map(|item| extract_string(&item, message))
            .collect();
    }

    Err(PyTypeError::new_err(message.to_owned()))
}

pub(crate) fn get_mapping_item<'py>(
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

pub(crate) fn ensure_supported_mapping_fields(
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

fn parse_sourcemap_setting(value: &Bound<'_, PyAny>, message: &str) -> PyResult<SourcemapSetting> {
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

pub(crate) fn parse_input(value: &Bound<'_, PyAny>) -> PyResult<Vec<InputItem>> {
    let message = "build() input must be a path, a sequence of paths, or a mapping of entry names to paths (str or os.PathLike)";

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
            return Err(PyValueError::new_err("build() input must not be empty"));
        }
        return Ok(input);
    }

    if let Ok(tuple) = value.cast::<PyTuple>() {
        let input = tuple
            .iter()
            .map(|item| extract_path_as_string(&item, message).map(InputItem::from))
            .collect::<PyResult<Vec<_>>>()?;
        if input.is_empty() {
            return Err(PyValueError::new_err("build() input must not be empty"));
        }
        return Ok(input);
    }

    if let Ok(mapping) = value.cast::<PyDict>() {
        let input = mapping
            .iter()
            .map(|(key, item)| {
                let key = extract_string(&key, "build() input mapping keys must be strings")?;
                let import = extract_path_as_string(&item, message)?;
                Ok(InputItem {
                    name: Some(key),
                    import,
                })
            })
            .collect::<PyResult<Vec<_>>>()?;
        if input.is_empty() {
            return Err(PyValueError::new_err("build() input must not be empty"));
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
    list.iter()
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
        .map_err(|_| PyTypeError::new_err(format!("{container}.replacements must be a list")))?;
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

pub(crate) fn parse_resolve_options(
    resolve: Option<&Bound<'_, PyAny>>,
) -> PyResult<Option<ResolveOptions>> {
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
            list.iter()
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
            list.iter()
                .map(|item| parse_extension_alias_item(&item, "Bundler.resolve.extension_alias[]"))
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
    let pattern_cls = re_mod
        .getattr("Pattern")
        .map_err(|_| PyRuntimeError::new_err("failed to load re.Pattern for external patterns"))?;
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

pub(crate) fn parse_external(
    py: Python<'_>,
    value: Option<&Bound<'_, PyAny>>,
) -> PyResult<Option<IsExternal>> {
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

pub(crate) fn parse_define(
    value: Option<&Bound<'_, PyAny>>,
) -> PyResult<Option<FxIndexMap<String, String>>> {
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
        let key = extract_string(
            &pair.get_item(0)?,
            "Bundler.define pair keys must be strings",
        )?;
        let val = extract_string(
            &pair.get_item(1)?,
            "Bundler.define pair values must be strings",
        )?;
        map.insert(key, val);
    }
    Ok(Some(map))
}

pub(crate) fn parse_inject(
    value: Option<&Bound<'_, PyAny>>,
) -> PyResult<Option<Vec<InjectImport>>> {
    let Some(value) = value else {
        return Ok(None);
    };
    let list = value.cast::<PyList>().map_err(|_| {
        PyTypeError::new_err("Bundler.inject must be a list of inject import mappings")
    })?;
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
            let imported = extract_string(&imported, "Bundler.inject[].imported must be a string")?;
            let alias = get_mapping_item(mapping, &["alias"])?
                .map(|a| extract_string(&a, "Bundler.inject[].alias must be a string"))
                .transpose()?;
            out.push(InjectImport::Named {
                imported,
                alias,
                from,
            });
        } else {
            let alias = get_mapping_item(mapping, &["alias"])?
                .ok_or_else(|| PyValueError::new_err("namespace inject requires alias and from"))?;
            let alias = extract_string(&alias, "Bundler.inject[].alias must be a string")?;
            out.push(InjectImport::Namespace { alias, from });
        }
    }
    Ok(Some(out))
}

pub(crate) fn parse_tsconfig(value: Option<&Bound<'_, PyAny>>) -> PyResult<Option<TsConfig>> {
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

pub(crate) fn parse_platform(value: Option<&Bound<'_, PyAny>>) -> PyResult<Option<Platform>> {
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
    let s = extract_string(value, &format!("{label} must be 'always' or 'false'"))?;
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
    let s = extract_string(value, &format!("{label} must be 'always' or 'false'"))?;
    match s.as_str() {
        "always" => Ok(PropertyWriteSideEffects::Always),
        "false" => Ok(PropertyWriteSideEffects::False),
        _ => Err(PyValueError::new_err(format!(
            "{label} must be 'always' or 'false'"
        ))),
    }
}

pub(crate) fn parse_treeshake(
    value: Option<&Bound<'_, PyAny>>,
) -> PyResult<Option<TreeshakeOptions>> {
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

    let module_side_effects =
        get_mapping_item(mapping, &["moduleSideEffects", "module_side_effects"])?
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
                .map_err(|_| {
                    PyTypeError::new_err("Bundler.treeshake.annotations must be a boolean")
                })?
                .extract()
        })
        .transpose()?;

    let manual_pure_functions =
        get_mapping_item(mapping, &["manualPureFunctions", "manual_pure_functions"])?
            .map(|v| {
                let strings = extract_string_sequence(
                    &v,
                    "Bundler.treeshake.manual_pure_functions must be a sequence of strings",
                )?;
                Ok::<_, PyErr>(strings.into_iter().collect::<FxHashSet<_>>())
            })
            .transpose()?;

    let unknown_global_side_effects = get_mapping_item(
        mapping,
        &["unknownGlobalSideEffects", "unknown_global_side_effects"],
    )?
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

    let invalid_import_side_effects = get_mapping_item(
        mapping,
        &["invalidImportSideEffects", "invalid_import_side_effects"],
    )?
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
                .map_err(|_| {
                    PyTypeError::new_err(format!("{label}.entries_aware must be a boolean"))
                })?
                .extract()
        })
        .transpose()?;
    let entries_aware_merge_threshold = get_mapping_item(
        mapping,
        &[
            "entriesAwareMergeThreshold",
            "entries_aware_merge_threshold",
        ],
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

pub(crate) fn parse_manual_code_splitting(
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
            v.extract::<f64>().map_err(|_| {
                PyTypeError::new_err("Bundler.manual_code_splitting.min_size must be a float")
            })
        })
        .transpose()?;
    let max_size = get_mapping_item(mapping, &["maxSize", "max_size"])?
        .map(|v| {
            v.extract::<f64>().map_err(|_| {
                PyTypeError::new_err("Bundler.manual_code_splitting.max_size must be a float")
            })
        })
        .transpose()?;
    let min_module_size = get_mapping_item(mapping, &["minModuleSize", "min_module_size"])?
        .map(|v| {
            v.extract::<f64>().map_err(|_| {
                PyTypeError::new_err(
                    "Bundler.manual_code_splitting.min_module_size must be a float",
                )
            })
        })
        .transpose()?;
    let max_module_size = get_mapping_item(mapping, &["maxModuleSize", "max_module_size"])?
        .map(|v| {
            v.extract::<f64>().map_err(|_| {
                PyTypeError::new_err(
                    "Bundler.manual_code_splitting.max_module_size must be a float",
                )
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
            list.iter()
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

pub(crate) fn parse_devtools(
    devtools: Option<&Bound<'_, PyAny>>,
) -> PyResult<(bool, Option<String>)> {
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
    ensure_supported_mapping_fields(mapping, "Bundler.devtools", &["sessionId", "session_id"])?;

    let session_id = get_mapping_item(mapping, &["sessionId", "session_id"])?
        .map(|value| extract_string(&value, "Bundler.devtools.session_id must be a string"))
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
        let v = extract_string(
            &v,
            &format!("{container}.{key_label} values must be strings"),
        )?;
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
        return Ok(EsModuleFlag::from(
            value.cast::<PyBool>()?.extract::<bool>()?,
        ));
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
                .map_err(|_| {
                    PyTypeError::new_err(format!("{container}.symbols must be a boolean"))
                })?
                .extract()
        })
        .transpose()?
        .unwrap_or(true);
    Ok(GeneratedCodeOptions { symbols })
}

fn parse_comments_for_output(value: &Bound<'_, PyAny>, label: &str) -> PyResult<CommentsOptions> {
    if value.is_instance_of::<PyBool>() {
        let b = value.cast::<PyBool>()?.extract::<bool>()?;
        return Ok(CommentsOptions {
            legal: b,
            annotation: b,
            jsdoc: b,
        });
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

pub(crate) fn parse_output_config(
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
                &format!("{container}.entry_file_names must be a string or os.PathLike path",),
            )
        })
        .transpose()?;
    let chunk_file_names = get_mapping_item(mapping, &["chunkFileNames", "chunk_file_names"])?
        .map(|value| {
            extract_path_as_string(
                &value,
                &format!("{container}.chunk_file_names must be a string or os.PathLike path",),
            )
        })
        .transpose()?;
    let asset_file_names = get_mapping_item(mapping, &["assetFileNames", "asset_file_names"])?
        .map(|value| {
            extract_path_as_string(
                &value,
                &format!("{container}.asset_file_names must be a string or os.PathLike path",),
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
                PyTypeError::new_err(format!(
                    "{container}.globals must be a string-keyed mapping"
                ))
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
            .map(|v| {
                extract_string(
                    &v,
                    &format!("{container}.sourcemap_base_url must be a string"),
                )
            })
            .transpose()?;

    let sourcemap_debug_ids =
        get_mapping_item(mapping, &["sourcemapDebugIds", "sourcemap_debug_ids"])?
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
                extract_string(
                    &v,
                    &format!("{container}.preserve_modules_root must be a string"),
                )
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
                .map_err(|_| {
                    PyTypeError::new_err(format!("{container}.clean_dir must be a boolean"))
                })?
                .extract()
        })
        .transpose()?;

    let strict_execution_order =
        get_mapping_item(mapping, &["strictExecutionOrder", "strict_execution_order"])?
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

    let sanitize_file_name =
        get_mapping_item(mapping, &["sanitizeFileName", "sanitize_file_name"])?
            .map(|v| {
                if v.is_instance_of::<PyBool>() {
                    Ok(SanitizeFilename::from(
                        v.cast::<PyBool>()?.extract::<bool>()?,
                    ))
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
