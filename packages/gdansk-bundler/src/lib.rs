use std::{path::PathBuf, sync::Arc};

use pyo3::{
    exceptions::{PyNotImplementedError, PyRuntimeError, PyTypeError, PyValueError},
    prelude::*,
    types::{PyBool, PyBytes, PyDict, PyList, PyString, PyTuple},
};
use rolldown::{
    AssetFilenamesOutputOption, BundleOutput, Bundler as RolldownBundler, BundlerOptions,
    ChunkFilenamesOutputOption, DevtoolsOptions, InputItem, OutputFormat, ResolveOptions,
    SourceMapType,
};

const BUNDLER_CONTEXT_ALREADY_ACTIVE: &str = "BundlerContext is already active";
const BUNDLER_CONTEXT_NOT_ACTIVE: &str = "BundlerContext is not active";
const FIRST_MILESTONE_MESSAGE: &str =
    "is not supported in the first gdansk-bundler milestone";

#[derive(Clone, Debug)]
struct BundlerConfigState {
    input: Vec<InputItem>,
    cwd: Option<PathBuf>,
    resolve_condition_names: Option<Vec<String>>,
    devtools_enabled: bool,
    devtools_session_id: Option<String>,
    default_output: Option<OutputConfig>,
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

#[pyclass(module = "gdansk_bundler._core", frozen, subclass, skip_from_py_object)]
struct Bundler {
    config: Arc<BundlerConfigState>,
}

#[pyclass(module = "gdansk_bundler._core", unsendable, subclass, skip_from_py_object)]
struct BundlerContext {
    config: Arc<BundlerConfigState>,
    active: bool,
}

#[pyclass(module = "gdansk_bundler._core", subclass, skip_from_py_object)]
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
    let message = "Bundler.input must be a string path, a sequence of string paths, or a mapping of entry names to string paths";

    if value.is_instance_of::<PyString>() {
        let input = extract_string(value, message)?;
        return Ok(vec![InputItem::from(input)]);
    }

    if let Ok(list) = value.cast::<PyList>() {
        let input = list
            .iter()
            .map(|item| extract_string(&item, message).map(InputItem::from))
            .collect::<PyResult<Vec<_>>>()?;
        if input.is_empty() {
            return Err(PyValueError::new_err("Bundler.input must not be empty"));
        }
        return Ok(input);
    }

    if let Ok(tuple) = value.cast::<PyTuple>() {
        let input = tuple
            .iter()
            .map(|item| extract_string(&item, message).map(InputItem::from))
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
                let import = extract_string(&item, message)?;
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

    Err(PyTypeError::new_err(message.to_owned()))
}

fn parse_resolve_condition_names(resolve: Option<&Bound<'_, PyAny>>) -> PyResult<Option<Vec<String>>> {
    let Some(resolve) = resolve else {
        return Ok(None);
    };
    let mapping = resolve
        .cast::<PyDict>()
        .map_err(|_| PyTypeError::new_err("Bundler.resolve must be a mapping"))?;
    ensure_supported_mapping_fields(
        mapping,
        "Bundler.resolve",
        &["conditionNames", "condition_names"],
    )?;

    get_mapping_item(mapping, &["conditionNames", "condition_names"])?
        .map(|value| {
            extract_string_sequence(
                &value,
                "Bundler.resolve.condition_names must be a sequence of strings",
            )
        })
        .transpose()
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
        ],
    )?;

    let dir = get_mapping_item(mapping, &["dir"])?
        .map(|value| extract_string(&value, &format!("{container}.dir must be a string path")))
        .transpose()?;
    let file = get_mapping_item(mapping, &["file"])?
        .map(|value| extract_string(&value, &format!("{container}.file must be a string path")))
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
            extract_string(
                &value,
                &format!("{container}.entry_file_names must be a string"),
            )
        })
        .transpose()?;
    let chunk_file_names = get_mapping_item(mapping, &["chunkFileNames", "chunk_file_names"])?
        .map(|value| {
            extract_string(
                &value,
                &format!("{container}.chunk_file_names must be a string"),
            )
        })
        .transpose()?;
    let asset_file_names = get_mapping_item(mapping, &["assetFileNames", "asset_file_names"])?
        .map(|value| {
            extract_string(
                &value,
                &format!("{container}.asset_file_names must be a string"),
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

    Ok(Some(OutputConfig {
        dir,
        file,
        format,
        entry_file_names,
        chunk_file_names,
        asset_file_names,
        sourcemap,
        name,
    }))
}

impl BundlerConfigState {
    fn from_python(
        input: &Bound<'_, PyAny>,
        cwd: Option<String>,
        resolve: Option<&Bound<'_, PyAny>>,
        devtools: Option<&Bound<'_, PyAny>>,
        output: Option<&Bound<'_, PyAny>>,
        plugins: Option<&Bound<'_, PyAny>>,
        watch: Option<&Bound<'_, PyAny>>,
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
        let resolve_condition_names = parse_resolve_condition_names(resolve)?;
        let (devtools_enabled, devtools_session_id) = parse_devtools(devtools)?;
        let default_output = parse_output_config(output, "Bundler.output")?;

        Ok(Self {
            input,
            cwd: cwd.map(PathBuf::from),
            resolve_condition_names,
            devtools_enabled,
            devtools_session_id,
            default_output,
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
                if override_config.dir.is_some() {
                    base.dir = override_config.dir;
                }
                if override_config.file.is_some() {
                    base.file = override_config.file;
                }
                if override_config.format.is_some() {
                    base.format = override_config.format;
                }
                if override_config.entry_file_names.is_some() {
                    base.entry_file_names = override_config.entry_file_names;
                }
                if override_config.chunk_file_names.is_some() {
                    base.chunk_file_names = override_config.chunk_file_names;
                }
                if override_config.asset_file_names.is_some() {
                    base.asset_file_names = override_config.asset_file_names;
                }
                if override_config.sourcemap.is_some() {
                    base.sourcemap = override_config.sourcemap;
                }
                if override_config.name.is_some() {
                    base.name = override_config.name;
                }
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
        cwd: Some(cwd),
        ..Default::default()
    };

    if let Some(condition_names) = &config.resolve_condition_names {
        options.resolve = Some(ResolveOptions {
            condition_names: Some(condition_names.clone()),
            ..Default::default()
        });
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
    #[pyo3(signature = (*, input, cwd = None, resolve = None, devtools = None, output = None, plugins = None, watch = None))]
    fn new(
        py: Python<'_>,
        input: &Bound<'_, PyAny>,
        cwd: Option<String>,
        resolve: Option<Py<PyAny>>,
        devtools: Option<Py<PyAny>>,
        output: Option<Py<PyAny>>,
        plugins: Option<Py<PyAny>>,
        watch: Option<Py<PyAny>>,
    ) -> PyResult<Self> {
        let config = BundlerConfigState::from_python(
            input,
            cwd,
            resolve.as_ref().map(|value| value.bind(py)),
            devtools.as_ref().map(|value| value.bind(py)),
            output.as_ref().map(|value| value.bind(py)),
            plugins.as_ref().map(|value| value.bind(py)),
            watch.as_ref().map(|value| value.bind(py)),
        )?;

        Ok(Self {
            config: Arc::new(config),
        })
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
