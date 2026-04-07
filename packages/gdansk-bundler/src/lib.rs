use std::{path::PathBuf, sync::Arc};

use pyo3::{
    exceptions::{PyNotImplementedError, PyRuntimeError},
    prelude::*,
    types::PyBytes,
};
use rolldown::{
    AddonOutputOption, AssetFilenamesOutputOption, BundleOutput, Bundler as RolldownBundler,
    BundlerOptions, ChunkFilenamesOutputOption, CodeSplittingMode, CommentsOptions, DevtoolsOptions,
    EsModuleFlag, GeneratedCodeOptions, GlobalsOutputOption, HashCharacters, InjectImport, InputItem,
    IsExternal, LegalComments, ManualCodeSplittingOptions, OutputExports, OutputFormat,
    PathsOutputOption, Platform, RawMinifyOptions, ResolveOptions, SanitizeFilename, SourceMapType,
    StrictMode, TreeshakeOptions, TsConfig,
};
use rolldown_plugin::__inner::SharedPluginable;
use rolldown_utils::indexmap::FxIndexMap;
use rustc_hash::FxHashMap;

const BUNDLER_CONTEXT_ALREADY_ACTIVE: &str = "BundlerContext is already active";
const BUNDLER_CONTEXT_NOT_ACTIVE: &str = "BundlerContext is not active";
const FIRST_MILESTONE_MESSAGE: &str =
    "is not supported in the first gdansk-bundler milestone";

#[derive(Clone, Debug)]
pub(crate) struct BundlerConfigState {
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
    plugins: Vec<SharedPluginable>,
}

#[derive(Clone, Debug, Default)]
pub(crate) struct OutputConfig {
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
pub(crate) enum SourcemapSetting {
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
    session_write: Option<bool>,
    active: bool,
}

#[pyclass(module = "gdansk_bundler._core", skip_from_py_object)]
struct AsyncBundlerContext {
    config: Arc<BundlerConfigState>,
    session_write: Option<bool>,
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

pub(crate) fn unsupported_feature_error(path: &str) -> PyErr {
    PyNotImplementedError::new_err(format!("{path} {FIRST_MILESTONE_MESSAGE}"))
}

mod plugin;
mod boundary;

impl BundlerConfigState {
    #[allow(clippy::too_many_arguments)]
    fn from_python(
        py: Python<'_>,
        cwd: Option<&Bound<'_, PyAny>>,
        resolve: Option<&Bound<'_, PyAny>>,
        devtools: Option<&Bound<'_, PyAny>>,
        output: Option<&Bound<'_, PyAny>>,
        plugins: Option<&Bound<'_, PyAny>>,
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
        boundary::bundler_config_from_python(
            py,
            cwd,
            resolve,
            devtools,
            output,
            plugins,
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
        )
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
    input: Vec<InputItem>,
    output_override: Option<OutputConfig>,
    write: Option<bool>,
) -> PyResult<(BundlerOptions, bool)> {
    let cwd = match &config.cwd {
        Some(cwd) => cwd.clone(),
        None => std::env::current_dir()
            .map_err(|err| PyRuntimeError::new_err(format!("failed to read current working directory: {err}")))?,
    };

    let mut options = BundlerOptions {
        input: Some(input),
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

    Ok((options, write.unwrap_or(config.default_output.is_some())))
}

async fn build_once(
    config: Arc<BundlerConfigState>,
    input: Vec<InputItem>,
    output_override: Option<OutputConfig>,
    write: Option<bool>,
) -> PyResult<BundlerOutput> {
    let (options, should_write) = create_bundler_options(config.as_ref(), input, output_override, write)?;
    let mut bundler = RolldownBundler::with_plugins(options, config.plugins.clone()).map_err(|errs| {
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
    py: Python<'_>,
    config: Arc<BundlerConfigState>,
    input: Vec<InputItem>,
    output_override: Option<OutputConfig>,
    write: Option<bool>,
) -> PyResult<BundlerOutput> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|err| PyRuntimeError::new_err(format!("failed to create tokio runtime: {err}")))?;

    // Plugin hooks call into Python from `tokio::task::spawn_blocking`. The GIL must not be held
    // while `block_on` waits, or the blocking thread deadlocks waiting for `Python::attach`.
    py.detach(|| runtime.block_on(build_once(config, input, output_override, write)))
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
        cwd = None,
        resolve = None,
        devtools = None,
        output = None,
        plugins = None,
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
        cwd: Option<Py<PyAny>>,
        resolve: Option<Py<PyAny>>,
        devtools: Option<Py<PyAny>>,
        output: Option<Py<PyAny>>,
        plugins: Option<Py<PyAny>>,
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
            cwd.as_ref().map(|value| value.bind(py)),
            resolve.as_ref().map(|value| value.bind(py)),
            devtools.as_ref().map(|value| value.bind(py)),
            output.as_ref().map(|value| value.bind(py)),
            plugins.as_ref().map(|value| value.bind(py)),
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

    #[pyo3(signature = (*, write = None, watch = None))]
    fn __call__(
        slf: PyRef<'_, Self>,
        py: Python<'_>,
        write: Option<bool>,
        watch: Option<Py<PyAny>>,
    ) -> PyResult<Py<BundlerContext>> {
        if let Some(watch) = watch.as_ref() {
            boundary::validate_watch(Some(&watch.bind(py)))?;
        } else {
            boundary::validate_watch(None)?;
        }
        Py::new(
            py,
            BundlerContext {
                config: Arc::clone(&slf.config),
                session_write: write,
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
            session_write: None,
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

    #[pyo3(signature = (input, output = None, *, write = None))]
    fn __call__<'py>(
        &self,
        py: Python<'py>,
        input: &Bound<'py, PyAny>,
        output: Option<Py<PyAny>>,
        write: Option<bool>,
    ) -> PyResult<Bound<'py, PyAny>> {
        self.ensure_active()?;
        let input_items = boundary::parse_input(input)?;
        let output_override = output
            .as_ref()
            .map(|value| boundary::parse_output_config(Some(value.bind(py)), "BundlerContext.output"))
            .transpose()?
            .flatten();
        let effective_write = write.or(self.session_write);
        let output = build_once_blocking(
            py,
            Arc::clone(&self.config),
            input_items,
            output_override,
            effective_write,
        )?;
        Ok(Py::new(py, output)?.into_bound(py).into_any())
    }
}

#[pymethods]
impl AsyncBundlerContext {
    #[new]
    #[pyo3(signature = (bundler, *, write = None, watch = None))]
    fn new(
        py: Python<'_>,
        bundler: PyRef<'_, Bundler>,
        write: Option<bool>,
        watch: Option<Py<PyAny>>,
    ) -> PyResult<Self> {
        if let Some(watch) = watch.as_ref() {
            boundary::validate_watch(Some(&watch.bind(py)))?;
        } else {
            boundary::validate_watch(None)?;
        }
        Ok(Self {
            config: Arc::clone(&bundler.config),
            session_write: write,
            active: false,
        })
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

    #[pyo3(signature = (input, output = None, *, write = None))]
    fn __call__<'py>(
        &self,
        py: Python<'py>,
        input: &Bound<'py, PyAny>,
        output: Option<Py<PyAny>>,
        write: Option<bool>,
    ) -> PyResult<Bound<'py, PyAny>> {
        self.ensure_active()?;
        let input_items = boundary::parse_input(input)?;
        let output_override = output
            .as_ref()
            .map(|value| boundary::parse_output_config(Some(value.bind(py)), "BundlerContext.output"))
            .transpose()?
            .flatten();
        let effective_write = write.or(self.session_write);
        let config = Arc::clone(&self.config);

        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let output = build_once(config, input_items, output_override, effective_write).await?;
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
        plugin::Plugin, AsyncBundlerContext, Bundler, BundlerContext, BundlerOutput, OutputAsset,
        OutputChunk,
    };
}
