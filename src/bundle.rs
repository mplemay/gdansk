use std::{
    borrow::Cow,
    collections::{BTreeMap, HashMap, HashSet},
    fmt, fs,
    hash::{Hash, Hasher},
    path::{Component, Path, PathBuf},
    sync::{Arc, Mutex},
};

use lightningcss::{
    bundler::{
        BundleErrorKind as CssBundleErrorKind, Bundler as CssBundler,
        FileProvider as CssFileProvider, ResolveResult, SourceProvider,
    },
    printer::PrinterOptions,
    stylesheet::{MinifyOptions, ParserOptions},
};
use pyo3::{
    basic::CompareOp,
    exceptions::{PyRuntimeError, PyValueError},
    prelude::*,
    types::PyModule,
};
use rolldown::{
    Bundler, BundlerOptions, InputItem, RawMinifyOptions, ResolveOptions,
    plugin::{
        __inner::SharedPluginable, HookBuildEndArgs, HookLoadArgs, HookLoadOutput, HookLoadReturn,
        HookResolveIdArgs, HookResolveIdOutput, HookResolveIdReturn, HookUsage,
        HookWriteBundleArgs, Plugin, PluginContext, PluginContextResolveOptions,
        SharedLoadPluginContext,
    },
};
use serde::Serialize;

const CLIENT_MODULE_PREFIX: &str = "gdansk:client:";
const CSS_STUB_PREFIX: &str = "gdansk:css-stub:";
const VIRTUAL_ROOT: &str = "__gdansk_virtual__";
const MANIFEST_FILE: &str = "gdansk-manifest.json";

type CssResultMap = Arc<Mutex<HashMap<String, Vec<String>>>>;

#[derive(Debug, Clone)]
struct BundleWidgetSpec {
    key: String,
    path: PathBuf,
}

#[pyclass(module = "gdansk._core", frozen, skip_from_py_object)]
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub(crate) struct BundleWidget {
    key: String,
    path: PathBuf,
}

#[derive(Debug, Clone)]
struct NormalizedWidget {
    key: String,
    path: PathBuf,
    source_path: PathBuf,
    client_name: String,
    client_module_id: String,
    client_output: String,
    css_output: String,
}

#[derive(Debug, Clone)]
enum BundleError {
    Validation(String),
    Runtime(String),
}

#[derive(Debug)]
enum CssProviderError {
    Io(std::io::Error),
    Bundle(BundleError),
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
struct CssGraphModule {
    imported_ids: Vec<String>,
}

struct CssSourceProvider {
    cwd: PathBuf,
    inner: CssFileProvider,
    virtual_sources: HashMap<PathBuf, String>,
    virtual_resolutions: HashMap<PathBuf, HashMap<String, PathBuf>>,
}

#[derive(Debug)]
struct GdanskBundlerPlugin {
    widgets: Vec<NormalizedWidget>,
    root: PathBuf,
    build_directory: String,
    output_root: PathBuf,
    minify: bool,
    css_stub_resolutions: Mutex<HashMap<String, String>>,
    pending_css_imports: Mutex<HashMap<String, Vec<String>>>,
    css_results: CssResultMap,
}

#[derive(Serialize)]
struct ManifestWidget {
    client: String,
    css: Vec<String>,
    entry: String,
}

#[derive(Serialize)]
struct GdanskManifest {
    #[serde(rename = "outDir")]
    out_dir: String,
    root: String,
    widgets: BTreeMap<String, ManifestWidget>,
}

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<BundleWidget>()?;
    module.add_function(wrap_pyfunction!(bundle, module)?)?;
    Ok(())
}

#[pymethods]
impl BundleWidget {
    #[new]
    #[pyo3(signature = (*, key, path))]
    fn new(key: String, path: PathBuf) -> PyResult<Self> {
        let key = normalize_key(&key).map_err(map_bundle_error)?;
        let path = normalize_widget_path(&path, &key).map_err(map_bundle_error)?;
        Ok(Self { key, path })
    }

    #[getter]
    fn key(&self) -> &str {
        &self.key
    }

    #[getter]
    fn path<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        to_py_path(py, &self.path)
    }

    fn __richcmp__(&self, other: PyRef<'_, Self>, op: CompareOp) -> bool {
        match op {
            CompareOp::Eq => *self == *other,
            CompareOp::Ne => *self != *other,
            _ => false,
        }
    }

    fn __hash__(&self) -> isize {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        self.hash(&mut hasher);
        hasher.finish() as isize
    }

    fn __repr__(&self) -> String {
        format!("BundleWidget(key={:?}, path={:?})", self.key, self.path)
    }
}

impl BundleWidget {
    fn as_spec(&self) -> BundleWidgetSpec {
        BundleWidgetSpec {
            key: self.key.clone(),
            path: self.path.clone(),
        }
    }
}

impl CssSourceProvider {
    fn with_virtual_entry(
        cwd: &Path,
        entry_path: PathBuf,
        entry_source: String,
        resolutions: HashMap<String, PathBuf>,
    ) -> Self {
        Self {
            cwd: cwd.to_path_buf(),
            inner: CssFileProvider::new(),
            virtual_sources: HashMap::from([(entry_path.clone(), entry_source)]),
            virtual_resolutions: HashMap::from([(entry_path, resolutions)]),
        }
    }
}

impl SourceProvider for CssSourceProvider {
    type Error = CssProviderError;

    fn read<'a>(&'a self, file: &Path) -> Result<&'a str, Self::Error> {
        if let Some(source) = self.virtual_sources.get(file) {
            return Ok(source.as_str());
        }

        self.inner.read(file).map_err(CssProviderError::from)
    }

    fn resolve(
        &self,
        specifier: &str,
        originating_file: &Path,
    ) -> Result<ResolveResult, Self::Error> {
        if let Some(resolutions) = self.virtual_resolutions.get(originating_file)
            && let Some(resolved) = resolutions.get(specifier)
        {
            return Ok(ResolveResult::File(resolved.clone()));
        }

        let importer_dir = originating_file.parent().unwrap_or(self.cwd.as_path());
        resolve_css_import_path(specifier, importer_dir, &self.cwd)
            .map(ResolveResult::File)
            .map_err(CssProviderError::from)
    }
}

impl fmt::Display for CssProviderError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(err) => err.fmt(f),
            Self::Bundle(err) => err.fmt(f),
        }
    }
}

impl std::error::Error for CssProviderError {}

impl From<std::io::Error> for CssProviderError {
    fn from(err: std::io::Error) -> Self {
        Self::Io(err)
    }
}

impl From<BundleError> for CssProviderError {
    fn from(err: BundleError) -> Self {
        Self::Bundle(err)
    }
}

impl BundleError {
    fn validation(message: impl Into<String>) -> Self {
        Self::Validation(message.into())
    }

    fn runtime(message: impl Into<String>) -> Self {
        Self::Runtime(message.into())
    }
}

impl fmt::Display for BundleError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Validation(message) | Self::Runtime(message) => write!(f, "{message}"),
        }
    }
}

impl std::error::Error for BundleError {}

impl GdanskBundlerPlugin {
    fn new(
        widgets: Vec<NormalizedWidget>,
        root: PathBuf,
        build_directory: String,
        minify: bool,
        css_results: CssResultMap,
    ) -> Self {
        let output_root = root.join(&build_directory);
        Self {
            widgets,
            root,
            build_directory,
            output_root,
            minify,
            css_stub_resolutions: Mutex::new(HashMap::new()),
            pending_css_imports: Mutex::new(HashMap::new()),
            css_results,
        }
    }

    fn widget_by_client_module_id(&self, id: &str) -> Option<&NormalizedWidget> {
        let key = id.strip_prefix(CLIENT_MODULE_PREFIX)?;
        self.widgets.iter().find(|widget| widget.key == key)
    }

    fn widget_by_client_importer(&self, importer: &str) -> Option<&NormalizedWidget> {
        self.widget_by_client_module_id(importer)
    }

    fn resolve_css_stub_id(specifier: &str, importer: Option<&str>) -> String {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        importer.hash(&mut hasher);
        specifier.hash(&mut hasher);
        format!("{CSS_STUB_PREFIX}{:016x}", hasher.finish())
    }

    async fn resolve_css_import(
        &self,
        ctx: &PluginContext,
        args: &HookResolveIdArgs<'_>,
    ) -> HookResolveIdReturn {
        if !args.specifier.ends_with(".css") {
            return Ok(None);
        }

        let resolution = match ctx
            .resolve(
                args.specifier,
                args.importer,
                Some(PluginContextResolveOptions::default()),
            )
            .await
        {
            Ok(resolution) => resolution,
            Err(err) => {
                return Err(std::io::Error::other(format!(
                    "failed to resolve css import \"{}\": {err}",
                    args.specifier
                ))
                .into());
            }
        };

        let resolved = match resolution {
            Ok(resolved) => resolved,
            Err(err) => {
                return Err(std::io::Error::other(format!(
                    "failed to resolve css import \"{}\": {err}",
                    args.specifier
                ))
                .into());
            }
        };

        if !resolved.id.as_str().ends_with(".css") {
            return Ok(None);
        }

        let virtual_id = Self::resolve_css_stub_id(args.specifier, args.importer);
        self.css_stub_resolutions
            .lock()
            .expect("css graph poisoned")
            .insert(virtual_id.clone(), resolved.id.to_string());

        Ok(Some(HookResolveIdOutput::from_id(virtual_id)))
    }

    fn collect_css_imports_for_widgets(
        &self,
        ctx: &PluginContext,
    ) -> Result<HashMap<String, Vec<String>>, BundleError> {
        let mut modules = HashMap::new();
        let mut entry_module_ids = Vec::new();

        for module_id in ctx.get_module_ids() {
            if let Some(module_info) = ctx.get_module_info(module_id.as_ref()) {
                if module_info.is_entry {
                    entry_module_ids.push(module_id.to_string());
                }
                modules.insert(
                    module_id.to_string(),
                    CssGraphModule {
                        imported_ids: module_info
                            .imported_ids
                            .iter()
                            .map(ToString::to_string)
                            .collect(),
                    },
                );
            }
        }

        let css_stub_resolutions = self
            .css_stub_resolutions
            .lock()
            .expect("css graph poisoned")
            .clone();

        self.widgets
            .iter()
            .map(|widget| {
                let entry_id =
                    find_widget_entry_module_id(widget, &entry_module_ids).ok_or_else(|| {
                        BundleError::runtime(format!(
                            "failed to find client entry in module graph: {}",
                            widget.key
                        ))
                    })?;
                Ok((
                    widget.key.clone(),
                    collect_entry_css_imports(&entry_id, &modules, &css_stub_resolutions),
                ))
            })
            .collect()
    }

    fn write_css_outputs(&self) -> Result<(), BundleError> {
        let pending = self
            .pending_css_imports
            .lock()
            .expect("css graph poisoned")
            .clone();

        let mut css_results = self.css_results.lock().expect("css result map poisoned");
        for widget in &self.widgets {
            let css_imports = pending.get(&widget.key).cloned().unwrap_or_default();
            if css_imports.is_empty() {
                css_results.insert(widget.key.clone(), Vec::new());
                continue;
            }

            let mut bundled = render_css_bundle(&css_imports, &self.root, self.minify)?;
            if !bundled.ends_with('\n') {
                bundled.push('\n');
            }

            let output_path = self.output_root.join(&widget.css_output);
            if let Some(parent) = output_path.parent() {
                fs::create_dir_all(parent).map_err(|err| {
                    BundleError::runtime(format!(
                        "failed to create css output directory {}: {err}",
                        parent.display()
                    ))
                })?;
            }
            fs::write(&output_path, bundled).map_err(|err| {
                BundleError::runtime(format!(
                    "failed to write css output {}: {err}",
                    output_path.display()
                ))
            })?;
            css_results.insert(
                widget.key.clone(),
                vec![format!("{}/{}", self.build_directory, widget.css_output)],
            );
        }

        Ok(())
    }
}

impl Plugin for GdanskBundlerPlugin {
    fn name(&self) -> Cow<'static, str> {
        Cow::Borrowed("gdansk:bundle")
    }

    async fn resolve_id(
        &self,
        ctx: &PluginContext,
        args: &HookResolveIdArgs<'_>,
    ) -> HookResolveIdReturn {
        if self.widget_by_client_module_id(args.specifier).is_some() {
            return Ok(Some(HookResolveIdOutput::from_id(args.specifier)));
        }

        if let Some(importer) = args.importer
            && let Some(widget) = self.widget_by_client_importer(importer)
            && args.specifier.starts_with('.')
        {
            let resolved = path_to_utf8(&widget.source_path, "virtual client import")
                .map_err(|err| std::io::Error::other(err.to_string()))?;
            return Ok(Some(HookResolveIdOutput::from_id(resolved)));
        }

        self.resolve_css_import(ctx, args).await
    }

    async fn load(&self, _ctx: SharedLoadPluginContext, args: &HookLoadArgs<'_>) -> HookLoadReturn {
        if let Some(widget) = self.widget_by_client_module_id(args.id) {
            let source = client_wrapper_source(&self.root, widget)
                .map_err(|err| std::io::Error::other(err.to_string()))?;
            return Ok(Some(HookLoadOutput {
                code: source.into(),
                ..Default::default()
            }));
        }

        if args.id.starts_with(CSS_STUB_PREFIX) {
            return Ok(Some(HookLoadOutput {
                code: "export {};".into(),
                ..Default::default()
            }));
        }

        Ok(None)
    }

    async fn build_end(
        &self,
        ctx: &PluginContext,
        _args: Option<&HookBuildEndArgs<'_>>,
    ) -> rolldown::plugin::HookNoopReturn {
        let imports = self
            .collect_css_imports_for_widgets(ctx)
            .map_err(|err| std::io::Error::other(err.to_string()))?;
        *self.pending_css_imports.lock().expect("css graph poisoned") = imports;
        Ok(())
    }

    async fn write_bundle(
        &self,
        _ctx: &PluginContext,
        _args: &mut HookWriteBundleArgs<'_>,
    ) -> rolldown::plugin::HookNoopReturn {
        self.write_css_outputs()
            .map_err(|err| std::io::Error::other(err.to_string()))?;
        Ok(())
    }

    fn register_hook_usage(&self) -> HookUsage {
        HookUsage::ResolveId | HookUsage::Load | HookUsage::BuildEnd | HookUsage::WriteBundle
    }
}

fn to_py_path<'py>(py: Python<'py>, path: &Path) -> PyResult<Bound<'py, PyAny>> {
    let pathlib = PyModule::import(py, "pathlib")?;
    pathlib.getattr("Path")?.call1((path,))
}

fn path_to_utf8(path: &Path, label: &str) -> Result<String, BundleError> {
    path.to_str().map(ToOwned::to_owned).ok_or_else(|| {
        BundleError::validation(format!(
            "{label} must be UTF-8 encodable: {}",
            path.display()
        ))
    })
}

fn to_posix_path(path: &Path) -> Result<String, BundleError> {
    Ok(path_to_utf8(path, "path")?.replace('\\', "/"))
}

fn normalize_key(key: &str) -> Result<String, BundleError> {
    if key.starts_with('/') || key.contains('\\') {
        return Err(BundleError::validation(
            "widget key must be a relative POSIX path",
        ));
    }

    let cleaned = key.trim().trim_matches('/');
    if cleaned.is_empty() {
        return Err(BundleError::validation("widget key must not be empty"));
    }

    let parts = cleaned.split('/').collect::<Vec<_>>();
    if parts.iter().any(|part| matches!(*part, "" | "." | "..")) {
        return Err(BundleError::validation(
            "widget key must not contain empty or traversal path segments",
        ));
    }

    Ok(parts.join("/"))
}

fn normalize_relative_directory(directory: &str) -> Result<String, BundleError> {
    if directory.starts_with('/') || directory.contains('\\') {
        return Err(BundleError::validation(
            "build directory must be a relative POSIX path without traversal segments",
        ));
    }

    let cleaned = directory.trim().trim_matches('/');
    if cleaned.is_empty() {
        return Err(BundleError::validation("build directory must not be empty"));
    }

    let parts = cleaned.split('/').collect::<Vec<_>>();
    if parts.iter().any(|part| matches!(*part, "" | "." | "..")) {
        return Err(BundleError::validation(
            "build directory must be a relative POSIX path without traversal segments",
        ));
    }

    Ok(parts.join("/"))
}

fn normalize_widget_path(path: &Path, key: &str) -> Result<PathBuf, BundleError> {
    if path.is_absolute() {
        return Err(BundleError::validation(
            "widget path must be relative to the widgets directory",
        ));
    }

    let posix = to_posix_path(path)?;
    if posix.contains('\\') {
        return Err(BundleError::validation(
            "widget path must use POSIX separators",
        ));
    }

    let parts = posix.split('/').collect::<Vec<_>>();
    if parts.iter().any(|part| matches!(*part, "" | "." | "..")) {
        return Err(BundleError::validation(
            "widget path must not contain empty or traversal path segments",
        ));
    }

    let file_name = parts.last().copied().unwrap_or_default();
    if !matches!(file_name, "widget.tsx" | "widget.jsx") {
        return Err(BundleError::validation(
            "widget path must point to a widget.tsx or widget.jsx file",
        ));
    }

    let path_key = parts[..parts.len() - 1].join("/");
    if path_key != key {
        return Err(BundleError::validation(format!(
            "widget path parent ({path_key}) must match widget key ({key})"
        )));
    }

    Ok(PathBuf::from(posix))
}

fn canonicalize_existing_file(path: &Path, label: &str) -> Result<PathBuf, BundleError> {
    if !path.exists() {
        return Err(BundleError::validation(format!(
            "{label} does not exist: {}",
            path.display()
        )));
    }

    if !path.is_file() {
        return Err(BundleError::validation(format!(
            "{label} is not a file: {}",
            path.display()
        )));
    }

    let canonical = path.canonicalize().map_err(|err| {
        BundleError::runtime(format!(
            "failed to canonicalize {label} {}: {err}",
            path.display()
        ))
    })?;
    Ok(dunce::simplified(&canonical).to_path_buf())
}

fn split_package_specifier(specifier: &str) -> Option<(&str, Option<&str>)> {
    if specifier.starts_with("./")
        || specifier.starts_with("../")
        || Path::new(specifier).is_absolute()
    {
        return None;
    }

    if let Some(remainder) = specifier.strip_prefix('@') {
        let (scope, tail) = remainder.split_once('/')?;
        let (name, subpath) = match tail.split_once('/') {
            Some((name, subpath)) => (name, Some(subpath)),
            None => (tail, None),
        };
        return Some((&specifier[..scope.len() + name.len() + 2], subpath));
    }

    match specifier.split_once('/') {
        Some((package_name, subpath)) => Some((package_name, Some(subpath))),
        None => Some((specifier, None)),
    }
}

fn find_node_modules_package_dir(
    package_name: &str,
    importer_dir: &Path,
    cwd: &Path,
) -> Option<PathBuf> {
    let mut current = Some(importer_dir);
    while let Some(directory) = current {
        let candidate = directory.join("node_modules").join(package_name);
        if candidate.is_dir() {
            return Some(candidate);
        }

        if directory == cwd {
            break;
        }

        current = directory.parent().filter(|parent| parent.starts_with(cwd));
    }

    None
}

fn extract_style_export_target<'a>(
    entry: &'a serde_json::Value,
    specifier: &str,
    export_key: &str,
) -> Result<&'a str, BundleError> {
    match entry {
        serde_json::Value::String(path) => Ok(path),
        serde_json::Value::Object(_) => entry
            .get("style")
            .and_then(serde_json::Value::as_str)
            .ok_or_else(|| {
                BundleError::validation(format!(
                    "package \"{specifier}\" does not define exports[\"{export_key}\"].style"
                ))
            }),
        _ => Err(BundleError::validation(format!(
            "package \"{specifier}\" has an unsupported exports[\"{export_key}\"] value"
        ))),
    }
}

fn resolve_package_style_export(
    package_dir: &Path,
    specifier: &str,
    subpath: Option<&str>,
) -> Result<PathBuf, BundleError> {
    let package_json_path = package_dir.join("package.json");
    let package_json = fs::read_to_string(&package_json_path).map_err(|err| {
        BundleError::runtime(format!(
            "failed to read package.json for css import \"{specifier}\": {} ({err})",
            package_json_path.display()
        ))
    })?;
    let parsed: serde_json::Value = serde_json::from_str(&package_json).map_err(|err| {
        BundleError::runtime(format!(
            "failed to parse package.json for css import \"{specifier}\": {} ({err})",
            package_json_path.display()
        ))
    })?;
    let export_key = subpath
        .map(|value| format!("./{value}"))
        .unwrap_or_else(|| ".".to_string());
    let style_path = parsed
        .get("exports")
        .and_then(|exports| exports.get(&export_key))
        .ok_or_else(|| {
            BundleError::validation(format!(
                "package \"{specifier}\" does not define exports[\"{export_key}\"]"
            ))
        })
        .and_then(|entry| extract_style_export_target(entry, specifier, &export_key))?;

    Ok(package_dir.join(style_path))
}

fn resolve_css_import_path(
    specifier: &str,
    importer_dir: &Path,
    cwd: &Path,
) -> Result<PathBuf, BundleError> {
    if specifier.starts_with("./") || specifier.starts_with("../") {
        return canonicalize_existing_file(&importer_dir.join(specifier), "css import");
    }

    if Path::new(specifier).is_absolute() {
        return canonicalize_existing_file(Path::new(specifier), "css import");
    }

    let (package_name, subpath) = split_package_specifier(specifier).ok_or_else(|| {
        BundleError::validation(format!("failed to resolve css import \"{specifier}\""))
    })?;
    let package_dir =
        find_node_modules_package_dir(package_name, importer_dir, cwd).ok_or_else(|| {
            BundleError::validation(format!("failed to resolve css import \"{specifier}\""))
        })?;

    if let Some(subpath) = subpath {
        let candidate = package_dir.join(subpath);
        if candidate.exists() {
            return canonicalize_existing_file(&candidate, "css import");
        }
    }

    let style_path = resolve_package_style_export(&package_dir, specifier, subpath)?;
    canonicalize_existing_file(&style_path, "css import")
}

fn synthetic_css_bundle_entry(
    cwd: &Path,
    css_paths: &[PathBuf],
) -> (PathBuf, String, HashMap<String, PathBuf>) {
    let entry_path = cwd.join(".gdansk").join("__gdansk_virtual_bundle.css");
    let mut source = String::new();
    let mut resolutions = HashMap::with_capacity(css_paths.len());

    for (index, path) in css_paths.iter().enumerate() {
        let specifier = format!("__gdansk_virtual_import_{index}.css");
        source.push_str("@import \"");
        source.push_str(&specifier);
        source.push_str("\";\n");
        resolutions.insert(specifier, path.clone());
    }

    (entry_path, source, resolutions)
}

fn resolve_css_input_paths(css_paths: &[String], cwd: &Path) -> Result<Vec<PathBuf>, BundleError> {
    css_paths
        .iter()
        .map(|css_path| {
            let path = Path::new(css_path);
            let candidate = if path.is_absolute() {
                path.to_path_buf()
            } else {
                cwd.join(path)
            };
            canonicalize_existing_file(&candidate, "css import")
        })
        .collect()
}

fn render_css_bundle(
    css_paths: &[String],
    cwd: &Path,
    minify: bool,
) -> Result<String, BundleError> {
    let resolved_paths = resolve_css_input_paths(css_paths, cwd)?;
    let (entry_path, entry_source, resolutions) = synthetic_css_bundle_entry(cwd, &resolved_paths);
    let provider =
        CssSourceProvider::with_virtual_entry(cwd, entry_path.clone(), entry_source, resolutions);
    let parser_options = ParserOptions {
        filename: path_to_utf8(&entry_path, "css path")?,
        ..ParserOptions::default()
    };
    let mut bundler = CssBundler::new(&provider, None, parser_options);
    let mut stylesheet = bundler.bundle(&entry_path).map_err(|err| {
        let err_message = err.to_string();
        match err.kind {
            CssBundleErrorKind::ResolverError(provider_err) => match provider_err {
                CssProviderError::Bundle(bundle_err) => bundle_err,
                CssProviderError::Io(io_err) => BundleError::runtime(format!(
                    "failed to read css bundle input {}: {io_err}",
                    entry_path.display()
                )),
            },
            _ => BundleError::runtime(format!(
                "failed to bundle css for {}: {err_message}",
                entry_path.display()
            )),
        }
    })?;

    if minify {
        stylesheet.minify(MinifyOptions::default()).map_err(|err| {
            BundleError::runtime(format!(
                "failed to minify css bundle {}: {err}",
                entry_path.display()
            ))
        })?;
    }

    stylesheet
        .to_css(PrinterOptions {
            minify,
            ..PrinterOptions::default()
        })
        .map(|result| result.code)
        .map_err(|err| {
            BundleError::runtime(format!(
                "failed to serialize css bundle {}: {err}",
                entry_path.display()
            ))
        })
}

fn collect_entry_css_imports(
    entry_id: &str,
    modules: &HashMap<String, CssGraphModule>,
    css_stub_resolutions: &HashMap<String, String>,
) -> Vec<String> {
    fn visit(
        module_id: &str,
        modules: &HashMap<String, CssGraphModule>,
        css_stub_resolutions: &HashMap<String, String>,
        visited_modules: &mut HashSet<String>,
        visited_css: &mut HashSet<String>,
        ordered_css: &mut Vec<String>,
    ) {
        if !visited_modules.insert(module_id.to_owned()) {
            return;
        }

        let Some(module) = modules.get(module_id) else {
            return;
        };

        for imported_id in &module.imported_ids {
            if let Some(css_import) = css_stub_resolutions.get(imported_id) {
                if visited_css.insert(css_import.clone()) {
                    ordered_css.push(css_import.clone());
                }
                continue;
            }
            visit(
                imported_id,
                modules,
                css_stub_resolutions,
                visited_modules,
                visited_css,
                ordered_css,
            );
        }
    }

    let mut ordered_css = Vec::new();
    let mut visited_modules = HashSet::new();
    let mut visited_css = HashSet::new();
    visit(
        entry_id,
        modules,
        css_stub_resolutions,
        &mut visited_modules,
        &mut visited_css,
        &mut ordered_css,
    );
    ordered_css
}

fn find_widget_entry_module_id(
    widget: &NormalizedWidget,
    entry_module_ids: &[String],
) -> Option<String> {
    entry_module_ids
        .iter()
        .find(|module_id| {
            let normalized = module_id.replace('\\', "/");
            normalized == widget.client_module_id || normalized.ends_with(&widget.client_module_id)
        })
        .cloned()
}

fn synthetic_client_path(root: &Path, key: &str) -> PathBuf {
    root.join(VIRTUAL_ROOT)
        .join("client")
        .join(key)
        .join("client.tsx")
}

fn import_path(from: &Path, to: &Path) -> Result<String, BundleError> {
    let from_dir = from.parent().unwrap_or_else(|| Path::new(""));
    let relative = relative_path(from_dir, to);
    let relative = to_posix_path(&relative)?;
    Ok(if relative.starts_with('.') {
        relative
    } else {
        format!("./{relative}")
    })
}

fn relative_path(from_dir: &Path, to: &Path) -> PathBuf {
    let from_components = from_dir.components().collect::<Vec<_>>();
    let to_components = to.components().collect::<Vec<_>>();
    let common_len = from_components
        .iter()
        .zip(&to_components)
        .take_while(|(left, right)| left == right)
        .count();

    let mut relative = PathBuf::new();
    for component in &from_components[common_len..] {
        if matches!(component, Component::Normal(_)) {
            relative.push("..");
        }
    }
    for component in &to_components[common_len..] {
        if let Component::Normal(part) = component {
            relative.push(part);
        }
    }
    relative
}

fn client_wrapper_source(root: &Path, widget: &NormalizedWidget) -> Result<String, BundleError> {
    let synthetic_path = synthetic_client_path(root, &widget.key);
    let import_path = import_path(&synthetic_path, &widget.source_path)?;
    Ok(format!(
        r#"import React from "react";
import {{ createRoot, hydrateRoot }} from "react-dom/client";
import App from {import_path:?};

const root = document.getElementById("root");

if (!root) {{
  throw new Error("Gdansk expected a #root element for widget hydration.");
}}

const element = React.createElement(React.StrictMode, null, React.createElement(App));

if (root.hasChildNodes()) {{
  hydrateRoot(root, element);
}} else {{
  createRoot(root).render(element);
}}
"#
    ))
}

fn normalize_widgets(
    widgets: Vec<BundleWidgetSpec>,
    root: &Path,
) -> Result<Vec<NormalizedWidget>, BundleError> {
    if widgets.is_empty() {
        return Err(BundleError::validation(
            "widgets must not be empty; expected at least one widget entry",
        ));
    }

    let mut seen_keys = HashSet::new();
    let mut normalized = Vec::with_capacity(widgets.len());
    for widget in widgets {
        let key = normalize_key(&widget.key)?;
        let path = normalize_widget_path(&widget.path, &key)?;
        if !seen_keys.insert(key.clone()) {
            return Err(BundleError::validation(format!(
                "multiple widgets use the key \"{key}\""
            )));
        }

        let source_path = root.join("widgets").join(&path);
        if !source_path.is_file() {
            return Err(BundleError::validation(format!(
                "widget path does not exist: {}",
                source_path.display()
            )));
        }

        normalized.push(NormalizedWidget {
            key: key.clone(),
            path,
            source_path,
            client_name: format!("{key}/client"),
            client_module_id: format!("{CLIENT_MODULE_PREFIX}{key}"),
            client_output: format!("{key}/client.js"),
            css_output: format!("{key}/client.css"),
        });
    }

    normalized.sort_unstable_by(|left, right| left.key.cmp(&right.key));
    Ok(normalized)
}

fn parse_widgets_from_python(
    py: Python<'_>,
    widgets: Vec<Py<BundleWidget>>,
) -> Vec<BundleWidgetSpec> {
    widgets
        .into_iter()
        .map(|widget| widget.borrow(py).as_spec())
        .collect()
}

fn build_input_items(widgets: &[NormalizedWidget]) -> Vec<InputItem> {
    widgets
        .iter()
        .map(|widget| InputItem {
            name: Some(widget.client_name.clone()),
            import: widget.client_module_id.clone(),
        })
        .collect()
}

async fn bundle_impl(
    widgets: Vec<BundleWidgetSpec>,
    root: PathBuf,
    build_directory: String,
    minify: bool,
) -> Result<(), BundleError> {
    if !root.is_dir() {
        return Err(BundleError::validation(format!(
            "frontend root directory does not exist: {}",
            root.display()
        )));
    }

    let root = dunce::simplified(&root.canonicalize().map_err(|err| {
        BundleError::runtime(format!(
            "failed to canonicalize frontend root {}: {err}",
            root.display()
        ))
    })?)
    .to_path_buf();
    let build_directory = normalize_relative_directory(&build_directory)?;
    let output_root = root.join(&build_directory);
    let normalized = normalize_widgets(widgets, &root)?;
    let css_results = CssResultMap::default();
    let plugin = Arc::new(GdanskBundlerPlugin::new(
        normalized.clone(),
        root.clone(),
        build_directory.clone(),
        minify,
        Arc::clone(&css_results),
    )) as SharedPluginable;

    if output_root.exists() {
        fs::remove_dir_all(&output_root).map_err(|err| {
            BundleError::runtime(format!(
                "failed to remove build directory {}: {err}",
                output_root.display()
            ))
        })?;
    }
    fs::create_dir_all(&output_root).map_err(|err| {
        BundleError::runtime(format!(
            "failed to create build directory {}: {err}",
            output_root.display()
        ))
    })?;

    let mut bundler = Bundler::with_plugins(
        BundlerOptions {
            input: Some(build_input_items(&normalized)),
            cwd: Some(root.clone()),
            dir: Some(build_directory.clone()),
            entry_filenames: Some("[name].js".to_string().into()),
            chunk_filenames: Some("assets/[name]-[hash].js".to_string().into()),
            minify: Some(RawMinifyOptions::Bool(minify)),
            resolve: Some(ResolveOptions {
                condition_names: Some(vec![
                    "module".to_string(),
                    "browser".to_string(),
                    "import".to_string(),
                    "default".to_string(),
                    "style".to_string(),
                ]),
                ..ResolveOptions::default()
            }),
            ..BundlerOptions::default()
        },
        vec![plugin],
    )
    .map_err(|err| BundleError::runtime(format!("failed to initialize Rolldown bundler: {err}")))?;

    bundler
        .write()
        .await
        .map_err(|err| BundleError::runtime(format!("bundling failed: {err}")))?;

    write_manifest(
        &normalized,
        &root,
        &build_directory,
        &output_root,
        &css_results,
    )
}

fn write_manifest(
    widgets: &[NormalizedWidget],
    root: &Path,
    build_directory: &str,
    output_root: &Path,
    css_results: &CssResultMap,
) -> Result<(), BundleError> {
    let css_results = css_results.lock().expect("css result map poisoned");
    let manifest = GdanskManifest {
        out_dir: build_directory.to_string(),
        root: path_to_utf8(root, "frontend root")?,
        widgets: widgets
            .iter()
            .map(|widget| {
                (
                    widget.key.clone(),
                    ManifestWidget {
                        client: format!("{build_directory}/{}", widget.client_output),
                        css: css_results.get(&widget.key).cloned().unwrap_or_default(),
                        entry: to_posix_path(&widget.path)
                            .expect("normalized widget path should be UTF-8"),
                    },
                )
            })
            .collect(),
    };
    let manifest_path = output_root.join(MANIFEST_FILE);
    let json = serde_json::to_string_pretty(&manifest)
        .map_err(|err| BundleError::runtime(format!("failed to serialize manifest: {err}")))?;
    fs::write(&manifest_path, format!("{json}\n")).map_err(|err| {
        BundleError::runtime(format!(
            "failed to write manifest {}: {err}",
            manifest_path.display()
        ))
    })
}

fn map_bundle_error(err: BundleError) -> PyErr {
    match err {
        BundleError::Validation(message) => PyValueError::new_err(message),
        BundleError::Runtime(message) => PyRuntimeError::new_err(message),
    }
}

#[pyfunction(signature = (widgets, *, root, build_directory = "dist".to_string(), minify = true))]
pub(crate) fn bundle(
    py: Python<'_>,
    widgets: Vec<Py<BundleWidget>>,
    root: PathBuf,
    build_directory: String,
    minify: bool,
) -> PyResult<Bound<'_, PyAny>> {
    let widgets = parse_widgets_from_python(py, widgets);
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        bundle_impl(widgets, root, build_directory, minify)
            .await
            .map_err(map_bundle_error)?;
        Python::attach(|py| Ok(py.None()))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_invalid_widget_keys() {
        assert!(normalize_key("").is_err());
        assert!(normalize_key("../hello").is_err());
        assert!(normalize_key("hello//world").is_err());
        assert!(normalize_key("/hello").is_err());
    }

    #[test]
    fn normalizes_widget_specs() {
        let root = std::env::temp_dir().join(format!("gdansk-bundle-test-{}", std::process::id()));
        let widget_path = root.join("widgets").join("nested/page/widget.tsx");
        fs::create_dir_all(widget_path.parent().expect("widget parent"))
            .expect("create widget parent");
        fs::write(
            &widget_path,
            "export default function App() { return null; }\n",
        )
        .expect("write widget");

        let normalized = normalize_widgets(
            vec![BundleWidgetSpec {
                key: "nested/page".to_string(),
                path: PathBuf::from("nested/page/widget.tsx"),
            }],
            &root,
        )
        .expect("normalize widget");

        assert_eq!(normalized[0].client_name, "nested/page/client");
        assert_eq!(normalized[0].client_output, "nested/page/client.js");
        assert_eq!(normalized[0].css_output, "nested/page/client.css");

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn rejects_duplicate_widget_keys() {
        let root = std::env::temp_dir().join(format!(
            "gdansk-bundle-duplicate-test-{}",
            std::process::id()
        ));
        let widget_path = root.join("widgets").join("hello/widget.tsx");
        fs::create_dir_all(widget_path.parent().expect("widget parent"))
            .expect("create widget parent");
        fs::write(
            &widget_path,
            "export default function App() { return null; }\n",
        )
        .expect("write widget");

        let err = normalize_widgets(
            vec![
                BundleWidgetSpec {
                    key: "hello".to_string(),
                    path: PathBuf::from("hello/widget.tsx"),
                },
                BundleWidgetSpec {
                    key: "hello".to_string(),
                    path: PathBuf::from("hello/widget.tsx"),
                },
            ],
            &root,
        )
        .expect_err("expected duplicate key error");

        assert!(err.to_string().contains("multiple widgets"));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn creates_client_wrapper_source() {
        let root = PathBuf::from("/project/views");
        let widget = NormalizedWidget {
            key: "hello".to_string(),
            path: PathBuf::from("hello/widget.tsx"),
            source_path: PathBuf::from("/project/views/widgets/hello/widget.tsx"),
            client_name: "hello/client".to_string(),
            client_module_id: "gdansk:client:hello".to_string(),
            client_output: "hello/client.js".to_string(),
            css_output: "hello/client.css".to_string(),
        };

        let source = client_wrapper_source(&root, &widget).expect("wrapper source");

        assert!(source.contains("react-dom/client"));
        assert!(source.contains("../../../widgets/hello/widget.tsx"));
        assert!(source.contains("hydrateRoot"));
    }

    #[test]
    fn writes_manifest_with_css_results() {
        let root =
            std::env::temp_dir().join(format!("gdansk-manifest-test-{}", std::process::id()));
        let output = root.join("dist");
        fs::create_dir_all(&output).expect("create output");
        let css_results = CssResultMap::default();
        css_results.lock().expect("css results").insert(
            "hello".to_string(),
            vec!["dist/hello/client.css".to_string()],
        );
        let widgets = vec![NormalizedWidget {
            key: "hello".to_string(),
            path: PathBuf::from("hello/widget.tsx"),
            source_path: root.join("widgets/hello/widget.tsx"),
            client_name: "hello/client".to_string(),
            client_module_id: "gdansk:client:hello".to_string(),
            client_output: "hello/client.js".to_string(),
            css_output: "hello/client.css".to_string(),
        }];

        write_manifest(&widgets, &root, "dist", &output, &css_results).expect("write manifest");
        let manifest = fs::read_to_string(output.join(MANIFEST_FILE)).expect("read manifest");

        assert!(manifest.contains("\"outDir\": \"dist\""));
        assert!(manifest.contains("\"client\": \"dist/hello/client.js\""));
        assert!(manifest.contains("\"dist/hello/client.css\""));

        let _ = fs::remove_dir_all(root);
    }
}
