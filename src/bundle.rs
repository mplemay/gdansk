use std::{
    collections::HashMap,
    ffi::OsStr,
    fmt,
    hash::{Hash, Hasher},
    path::{Path, PathBuf},
};

#[cfg(not(test))]
use pyo3::{
    basic::CompareOp,
    exceptions::{PyRuntimeError, PyValueError},
    prelude::*,
    types::PyModule,
};
#[cfg(not(test))]
use rolldown::plugin::{
    __inner::SharedPluginable, HookLoadArgs, HookLoadOutput, HookLoadReturn, HookResolveIdArgs,
    HookResolveIdOutput, HookResolveIdReturn, HookUsage, Plugin, PluginContext,
    SharedLoadPluginContext,
};
#[cfg(not(test))]
use rolldown::{
    Bundler, BundlerOptions, ExperimentalOptions, InputItem, OutputFormat, ResolveOptions,
};
#[cfg(not(test))]
use rolldown_dev::{BundlerConfig, DevEngine, DevOptions, RebuildStrategy};
#[cfg(not(test))]
use std::{borrow::Cow, sync::Arc};

#[derive(Debug, Clone)]
struct ViewSpec {
    path: PathBuf,
    app: bool,
    ssr: bool,
}

#[cfg(not(test))]
#[pyclass(module = "gdansk._core", frozen, skip_from_py_object)]
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub(crate) struct View {
    path: PathBuf,
    app: bool,
    ssr: bool,
    client: PathBuf,
    server: Option<PathBuf>,
    css: PathBuf,
}

#[derive(Debug, Clone)]
struct NormalizedView {
    import: String,
    app: bool,
    ssr: bool,
    client_name: String,
    server_name: Option<String>,
}

#[derive(Debug, Clone)]
enum BundleError {
    Validation(String),
    Runtime(String),
}

const APP_ENTRYPOINT_QUERY: &str = "?gdansk-app-entry";
const SERVER_ENTRYPOINT_QUERY: &str = "?gdansk-server-entry";
const GDANSK_RUNTIME_SPECIFIER: &str = "gdansk:runtime";
#[cfg(not(test))]
const GDANSK_RUNTIME_MODULE_SOURCE: &str = include_str!("runtime.js");

fn derive_output_stems(path: &Path, app: bool, ssr: bool) -> (PathBuf, Option<PathBuf>) {
    if !app {
        let stem = path.with_extension("");
        let server = if ssr { Some(stem.clone()) } else { None };
        return (stem, server);
    }

    let mut tool_directory = PathBuf::new();
    if let Some(parent) = path.parent() {
        for component in parent.components().skip(1) {
            tool_directory.push(component.as_os_str());
        }
    }
    if tool_directory.as_os_str().is_empty() {
        tool_directory.push("client");
    }

    let client_stem = tool_directory.join("client");
    let server_stem = if ssr {
        Some(tool_directory.join("server"))
    } else {
        None
    };
    (client_stem, server_stem)
}

#[cfg(not(test))]
fn to_py_path<'py>(py: Python<'py>, path: &Path) -> PyResult<Bound<'py, PyAny>> {
    let pathlib = PyModule::import(py, "pathlib")?;
    pathlib.getattr("Path")?.call1((path,))
}

#[cfg(not(test))]
#[pymethods]
impl View {
    #[new]
    #[pyo3(signature = (*, path, app = false, ssr = false))]
    fn new(path: PathBuf, app: bool, ssr: bool) -> Self {
        let (client_stem, server_stem) = derive_output_stems(&path, app, ssr);
        Self {
            path,
            app,
            ssr,
            client: client_stem.with_extension("js"),
            server: server_stem.map(|stem| stem.with_extension("js")),
            css: client_stem.with_extension("css"),
        }
    }

    #[getter]
    fn path<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        to_py_path(py, &self.path)
    }

    #[getter]
    fn app(&self) -> bool {
        self.app
    }

    #[getter]
    fn ssr(&self) -> bool {
        self.ssr
    }

    #[getter]
    fn client<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        to_py_path(py, &self.client)
    }

    #[getter]
    fn server<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyAny>>> {
        self.server
            .as_deref()
            .map(|path| to_py_path(py, path))
            .transpose()
    }

    #[getter]
    fn css<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        to_py_path(py, &self.css)
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
        format!(
            "View(path={:?}, app={}, ssr={}, client={:?}, server={:?}, css={:?})",
            self.path, self.app, self.ssr, self.client, self.server, self.css
        )
    }
}

#[cfg(not(test))]
impl View {
    fn as_spec(&self) -> ViewSpec {
        ViewSpec {
            path: self.path.clone(),
            app: self.app,
            ssr: self.ssr,
        }
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

fn entry_import_for_client(import: &str, app: bool) -> String {
    if app {
        format!("{import}{APP_ENTRYPOINT_QUERY}")
    } else {
        import.to_owned()
    }
}

fn entry_import_for_server(import: &str) -> String {
    format!("{import}{SERVER_ENTRYPOINT_QUERY}")
}

fn build_client_input_item_fields(normalized: &[NormalizedView]) -> Vec<(String, String)> {
    normalized
        .iter()
        .map(|item| {
            (
                item.client_name.clone(),
                entry_import_for_client(&item.import, item.app),
            )
        })
        .collect()
}

fn build_server_input_item_fields(normalized: &[NormalizedView]) -> Vec<(String, String)> {
    normalized
        .iter()
        .filter(|item| item.ssr)
        .map(|item| {
            (
                item.server_name
                    .clone()
                    .expect("ssr view must have server name"),
                entry_import_for_server(&item.import),
            )
        })
        .collect()
}

fn server_entrypoint_wrapper_source(source_id: &str) -> Option<String> {
    let file_name = Path::new(source_id).file_name()?.to_str()?;
    let import_path = format!("./{file_name}");
    Some(format!(
        r#"import {{ createElement }} from "react";
import {{ renderToString }} from "react-dom/server";
import {{ setSsrHtml }} from "gdansk:runtime";
import App from "{import_path}";

setSsrHtml(renderToString(createElement(App)));
"#
    ))
}

#[cfg(not(test))]
struct DevEngineCloseGuard {
    engine: Option<Arc<DevEngine>>,
}

#[cfg(not(test))]
#[derive(Debug, Default)]
struct GdanskAppEntrypointPlugin;

#[cfg(not(test))]
impl GdanskAppEntrypointPlugin {
    fn source_id(id: &str) -> Option<&str> {
        id.strip_suffix(APP_ENTRYPOINT_QUERY)
    }

    fn wrapper_source(source_id: &str) -> Option<String> {
        let file_name = Path::new(source_id).file_name()?.to_str()?;
        let import_path = format!("./{file_name}");
        Some(format!(
            r#"import {{ StrictMode, createElement }} from "react";
import {{ createRoot, hydrateRoot }} from "react-dom/client";
import App from "{import_path}";

const root = document.getElementById("root");
if (!root) throw new Error("Expected #root element");
const element = createElement(StrictMode, null, createElement(App));
if (root.hasChildNodes()) {{
  hydrateRoot(root, element);
}} else {{
  createRoot(root).render(element);
}}
"#
        ))
    }
}

#[cfg(not(test))]
impl Plugin for GdanskAppEntrypointPlugin {
    fn name(&self) -> Cow<'static, str> {
        Cow::Borrowed("gdansk:app-entrypoint")
    }

    async fn resolve_id(
        &self,
        _ctx: &PluginContext,
        args: &HookResolveIdArgs<'_>,
    ) -> HookResolveIdReturn {
        if args.specifier.ends_with(APP_ENTRYPOINT_QUERY) {
            return Ok(Some(HookResolveIdOutput::from_id(args.specifier)));
        }
        Ok(None)
    }

    async fn load(&self, _ctx: SharedLoadPluginContext, args: &HookLoadArgs<'_>) -> HookLoadReturn {
        let Some(source_id) = Self::source_id(args.id) else {
            return Ok(None);
        };
        let Some(wrapper_source) = Self::wrapper_source(source_id) else {
            return Ok(None);
        };
        Ok(Some(HookLoadOutput {
            code: wrapper_source.into(),
            ..Default::default()
        }))
    }

    fn register_hook_usage(&self) -> HookUsage {
        HookUsage::ResolveId | HookUsage::Load
    }
}

#[cfg(not(test))]
#[derive(Debug, Default)]
struct GdanskServerEntrypointPlugin;

#[cfg(not(test))]
#[derive(Debug, Default)]
struct GdanskRuntimeModulePlugin;

#[cfg(not(test))]
impl GdanskServerEntrypointPlugin {
    fn source_id(id: &str) -> Option<&str> {
        id.strip_suffix(SERVER_ENTRYPOINT_QUERY)
    }

    fn wrapper_source(source_id: &str) -> Option<String> {
        server_entrypoint_wrapper_source(source_id)
    }
}

#[cfg(not(test))]
impl Plugin for GdanskRuntimeModulePlugin {
    fn name(&self) -> Cow<'static, str> {
        Cow::Borrowed("gdansk:runtime-module")
    }

    async fn resolve_id(
        &self,
        _ctx: &PluginContext,
        args: &HookResolveIdArgs<'_>,
    ) -> HookResolveIdReturn {
        if args.specifier == GDANSK_RUNTIME_SPECIFIER {
            return Ok(Some(HookResolveIdOutput::from_id(GDANSK_RUNTIME_SPECIFIER)));
        }
        Ok(None)
    }

    async fn load(&self, _ctx: SharedLoadPluginContext, args: &HookLoadArgs<'_>) -> HookLoadReturn {
        if args.id != GDANSK_RUNTIME_SPECIFIER {
            return Ok(None);
        }
        Ok(Some(HookLoadOutput {
            code: GDANSK_RUNTIME_MODULE_SOURCE.into(),
            ..Default::default()
        }))
    }

    fn register_hook_usage(&self) -> HookUsage {
        HookUsage::ResolveId | HookUsage::Load
    }
}

#[cfg(not(test))]
impl Plugin for GdanskServerEntrypointPlugin {
    fn name(&self) -> Cow<'static, str> {
        Cow::Borrowed("gdansk:server-entrypoint")
    }

    async fn resolve_id(
        &self,
        _ctx: &PluginContext,
        args: &HookResolveIdArgs<'_>,
    ) -> HookResolveIdReturn {
        if args.specifier.ends_with(SERVER_ENTRYPOINT_QUERY) {
            return Ok(Some(HookResolveIdOutput::from_id(args.specifier)));
        }
        Ok(None)
    }

    async fn load(&self, _ctx: SharedLoadPluginContext, args: &HookLoadArgs<'_>) -> HookLoadReturn {
        let Some(source_id) = Self::source_id(args.id) else {
            return Ok(None);
        };
        let Some(wrapper_source) = Self::wrapper_source(source_id) else {
            return Ok(None);
        };
        Ok(Some(HookLoadOutput {
            code: wrapper_source.into(),
            ..Default::default()
        }))
    }

    fn register_hook_usage(&self) -> HookUsage {
        HookUsage::ResolveId | HookUsage::Load
    }
}

#[cfg(not(test))]
fn client_entrypoint_plugins(include_app_entrypoint_plugin: bool) -> Vec<SharedPluginable> {
    if include_app_entrypoint_plugin {
        vec![Arc::new(GdanskAppEntrypointPlugin)]
    } else {
        vec![]
    }
}

#[cfg(not(test))]
fn server_entrypoint_plugins() -> Vec<SharedPluginable> {
    vec![
        Arc::new(GdanskRuntimeModulePlugin),
        Arc::new(GdanskServerEntrypointPlugin),
    ]
}

#[cfg(not(test))]
impl DevEngineCloseGuard {
    fn new(engine: Arc<DevEngine>) -> Self {
        Self {
            engine: Some(engine),
        }
    }

    fn disarm(&mut self) {
        self.engine = None;
    }
}

#[cfg(not(test))]
impl Drop for DevEngineCloseGuard {
    fn drop(&mut self) {
        let Some(engine) = self.engine.take() else {
            return;
        };

        let Ok(handle) = tokio::runtime::Handle::try_current() else {
            return;
        };

        handle.spawn(async move {
            let _ = engine.close().await;
        });
    }
}

#[cfg(not(test))]
fn py_runtime_error(context: &str, err: impl std::fmt::Display) -> PyErr {
    PyRuntimeError::new_err(format!("{context}: {err}"))
}

fn path_to_utf8(path: &Path, label: &str) -> Result<String, BundleError> {
    path.to_str().map(ToOwned::to_owned).ok_or_else(|| {
        BundleError::validation(format!(
            "{label} must be UTF-8 encodable: {}",
            path.display()
        ))
    })
}

fn normalize_relative_for_rolldown(path: &Path, label: &str) -> Result<String, BundleError> {
    let utf8 = path_to_utf8(path, label)?;
    Ok(utf8.replace('\\', "/"))
}

fn is_supported_jsx_extension(path: &Path) -> bool {
    path.extension()
        .and_then(|ext| ext.to_str())
        .is_some_and(|ext| ext.eq_ignore_ascii_case("tsx") || ext.eq_ignore_ascii_case("jsx"))
}

fn normalize_views(
    views: Vec<ViewSpec>,
    cwd: &Path,
    output_dir: &Path,
) -> Result<Vec<NormalizedView>, BundleError> {
    if views.is_empty() {
        return Err(BundleError::validation(
            "`views` must not be empty; expected at least one .tsx or .jsx file",
        ));
    }

    let cwd_canonical = dunce::simplified(&cwd.canonicalize().map_err(|err| {
        BundleError::runtime(format!(
            "failed to resolve current working directory {}: {err}",
            cwd.display()
        ))
    })?)
    .to_path_buf();

    let mut normalized_views = Vec::with_capacity(views.len());
    let mut output_collisions: HashMap<PathBuf, String> = HashMap::new();

    for provided_view in views {
        let provided_path = provided_view.path;
        let absolute_candidate = if provided_path.is_absolute() {
            provided_path.clone()
        } else {
            cwd.join(&provided_path)
        };

        if !absolute_candidate.exists() {
            return Err(BundleError::validation(format!(
                "input path does not exist: {}",
                provided_path.display()
            )));
        }

        if !absolute_candidate.is_file() {
            return Err(BundleError::validation(format!(
                "input path is not a file: {}",
                provided_path.display()
            )));
        }

        if !is_supported_jsx_extension(&absolute_candidate) {
            return Err(BundleError::validation(format!(
                "input path must end in .tsx or .jsx: {}",
                provided_path.display()
            )));
        }

        let canonical_input =
            dunce::simplified(&absolute_candidate.canonicalize().map_err(|err| {
                BundleError::runtime(format!(
                    "failed to canonicalize input {}: {err}",
                    provided_path.display()
                ))
            })?)
            .to_path_buf();

        let relative_path = canonical_input.strip_prefix(&cwd_canonical).map_err(|_| {
            BundleError::validation(format!(
                "input path must resolve inside cwd {}: {}",
                cwd_canonical.display(),
                canonical_input.display()
            ))
        })?;

        let import = normalize_relative_for_rolldown(relative_path, "input path")?;
        let key = import.clone();

        if provided_view.ssr && !provided_view.app {
            return Err(BundleError::validation(format!(
                "view cannot set ssr=true when app=false: {}",
                provided_path.display()
            )));
        }

        let (client_stem_path, server_stem_path) = if provided_view.app {
            let file_name = relative_path
                .file_name()
                .and_then(|name| name.to_str())
                .ok_or_else(|| {
                    BundleError::validation(format!(
                        "app views must target app.tsx or app.jsx: {}",
                        provided_path.display()
                    ))
                })?;
            if file_name != "app.tsx" && file_name != "app.jsx" {
                return Err(BundleError::validation(format!(
                    "app views must target app.tsx or app.jsx: {}",
                    provided_path.display()
                )));
            }

            let mut relative_components = relative_path.components();
            let starts_with_apps = relative_components
                .next()
                .is_some_and(|component| component.as_os_str() == OsStr::new("apps"));
            if !starts_with_apps {
                return Err(BundleError::validation(format!(
                    "app views must be inside an apps/ directory: {}",
                    provided_path.display()
                )));
            }

            let mut tool_directory = PathBuf::new();
            if let Some(parent) = relative_path.parent() {
                for component in parent.components().skip(1) {
                    tool_directory.push(component.as_os_str());
                }
            }
            if tool_directory.as_os_str().is_empty() {
                return Err(BundleError::validation(format!(
                    "app views must include at least one segment below apps/: {}",
                    provided_path.display()
                )));
            }

            let client_stem = tool_directory.join("client");
            let server_stem = if provided_view.ssr {
                Some(tool_directory.join("server"))
            } else {
                None
            };
            (client_stem, server_stem)
        } else {
            (relative_path.with_extension(""), None)
        };

        let client_js_path = client_stem_path.with_extension("js");
        let client_css_path = client_stem_path.with_extension("css");
        let client_name = normalize_relative_for_rolldown(&client_stem_path, "entry name")?;
        let _ = normalize_relative_for_rolldown(&client_js_path, "client output path")?;
        let _ = normalize_relative_for_rolldown(&client_css_path, "client css output path")?;

        if let Some(previous_view) = output_collisions.insert(client_js_path.clone(), key.clone()) {
            return Err(BundleError::validation(format!(
                "multiple views map to the same output {}: {} and {}",
                output_dir.join(&client_js_path).display(),
                previous_view,
                key
            )));
        }

        let server_name = if let Some(server_stem_path) = server_stem_path {
            let server_js_path = server_stem_path.with_extension("js");
            if let Some(previous_view) =
                output_collisions.insert(server_js_path.clone(), key.clone())
            {
                return Err(BundleError::validation(format!(
                    "multiple views map to the same output {}: {} and {}",
                    output_dir.join(&server_js_path).display(),
                    previous_view,
                    key
                )));
            }
            let _ = normalize_relative_for_rolldown(&server_js_path, "server output path")?;
            Some(normalize_relative_for_rolldown(
                &server_stem_path,
                "server entry name",
            )?)
        } else {
            None
        };

        normalized_views.push(NormalizedView {
            import,
            app: provided_view.app,
            ssr: provided_view.ssr,
            client_name,
            server_name,
        });
    }

    normalized_views.sort_unstable_by(|left, right| left.import.cmp(&right.import));
    Ok(normalized_views)
}

#[cfg(not(test))]
fn map_bundle_error(err: BundleError) -> PyErr {
    match err {
        BundleError::Validation(message) => PyValueError::new_err(message),
        BundleError::Runtime(message) => PyRuntimeError::new_err(message),
    }
}

#[cfg(not(test))]
fn parse_views_from_python(py: Python<'_>, views: Vec<Py<View>>) -> Vec<ViewSpec> {
    views
        .into_iter()
        .map(|view| view.borrow(py).as_spec())
        .collect()
}

#[cfg(not(test))]
fn build_input_items(fields: Vec<(String, String)>) -> Vec<InputItem> {
    fields
        .into_iter()
        .map(|(name, import)| InputItem {
            name: Some(name),
            import,
        })
        .collect()
}

#[cfg(not(test))]
async fn run_bundler(
    input_items: Vec<InputItem>,
    cwd: PathBuf,
    output_dir_string: String,
    minify: bool,
    dev: bool,
    format: Option<OutputFormat>,
    plugins: Vec<SharedPluginable>,
) -> Result<(), PyErr> {
    let mut options = BundlerOptions {
        input: Some(input_items),
        cwd: Some(cwd),
        dir: Some(output_dir_string),
        entry_filenames: Some("[name].js".to_string().into()),
        css_entry_filenames: Some("[name].css".to_string().into()),
        minify: Some(minify.into()),
        format,
        resolve: Some(ResolveOptions {
            condition_names: Some(vec!["module".to_string(), "style".to_string()]),
            ..Default::default()
        }),
        ..Default::default()
    };

    if dev {
        options.experimental = Some(ExperimentalOptions {
            incremental_build: Some(true),
            ..Default::default()
        });

        let bundler_config = BundlerConfig::new(options, plugins);
        let dev_engine = Arc::new(
            DevEngine::new(
                bundler_config,
                DevOptions {
                    rebuild_strategy: Some(RebuildStrategy::Always),
                    ..Default::default()
                },
            )
            .map_err(|err| py_runtime_error("failed to initialize DevEngine", err))?,
        );

        let mut close_guard = DevEngineCloseGuard::new(Arc::clone(&dev_engine));

        dev_engine
            .run()
            .await
            .map_err(|err| py_runtime_error("failed to start DevEngine", err))?;
        dev_engine
            .wait_for_close()
            .await
            .map_err(|err| py_runtime_error("DevEngine exited with an error", err))?;

        close_guard.disarm();
        return Ok(());
    }

    let mut bundler = Bundler::with_plugins(options, plugins)
        .map_err(|err| py_runtime_error("failed to initialize Bundler", err))?;
    bundler
        .write()
        .await
        .map_err(|err| py_runtime_error("bundling failed", err))?;
    Ok(())
}

#[cfg(not(test))]
#[pyfunction(signature = (views, dev = false, minify = true, output = None, cwd = None))]
pub(crate) fn bundle(
    py: Python<'_>,
    views: Vec<Py<View>>,
    dev: bool,
    minify: bool,
    output: Option<PathBuf>,
    cwd: Option<PathBuf>,
) -> PyResult<Bound<'_, PyAny>> {
    let parsed_views = parse_views_from_python(py, views);

    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        let cwd = match cwd {
            Some(dir) => dunce::simplified(
                &dir.canonicalize()
                    .map_err(|err| py_runtime_error("failed to resolve provided cwd", err))?,
            )
            .to_path_buf(),
            None => std::env::current_dir()
                .map_err(|err| py_runtime_error("failed to read current working directory", err))?,
        };
        let output_dir = output.unwrap_or_else(|| PathBuf::from(".gdansk"));
        let output_dir_string =
            path_to_utf8(&output_dir, "output path").map_err(map_bundle_error)?;
        let normalized =
            normalize_views(parsed_views, &cwd, &output_dir).map_err(map_bundle_error)?;

        let client_items = build_input_items(build_client_input_item_fields(&normalized));
        let server_items = build_input_items(build_server_input_item_fields(&normalized));
        let has_app_entries = normalized.iter().any(|view| view.app);

        if dev {
            if server_items.is_empty() {
                run_bundler(
                    client_items,
                    cwd,
                    output_dir_string,
                    minify,
                    dev,
                    None,
                    client_entrypoint_plugins(has_app_entries),
                )
                .await?;
            } else {
                tokio::try_join!(
                    run_bundler(
                        client_items,
                        cwd.clone(),
                        output_dir_string.clone(),
                        minify,
                        dev,
                        None,
                        client_entrypoint_plugins(has_app_entries),
                    ),
                    run_bundler(
                        server_items,
                        cwd,
                        output_dir_string,
                        minify,
                        dev,
                        Some(OutputFormat::Iife),
                        server_entrypoint_plugins(),
                    ),
                )?;
            }
            return Python::attach(|py| Ok(py.None()));
        }

        run_bundler(
            client_items,
            cwd.clone(),
            output_dir_string.clone(),
            minify,
            dev,
            None,
            client_entrypoint_plugins(has_app_entries),
        )
        .await?;
        if !server_items.is_empty() {
            run_bundler(
                server_items,
                cwd,
                output_dir_string,
                minify,
                dev,
                Some(OutputFormat::Iife),
                server_entrypoint_plugins(),
            )
            .await?;
        }
        Python::attach(|py| Ok(py.None()))
    })
}

#[cfg(test)]
mod tests {
    use std::{
        fs,
        sync::atomic::{AtomicU64, Ordering},
    };

    use super::*;

    static NEXT_TEMP_ID: AtomicU64 = AtomicU64::new(0);

    struct TempProject {
        root: PathBuf,
    }

    impl TempProject {
        fn new() -> Self {
            let id = NEXT_TEMP_ID.fetch_add(1, Ordering::Relaxed);
            let root =
                std::env::temp_dir().join(format!("gdansk-test-{}-{}", std::process::id(), id));
            fs::create_dir_all(&root).expect("failed to create temp project root");
            Self { root }
        }

        fn create_file(&self, relative: &str) {
            let file_path = self.root.join(relative);
            if let Some(parent) = file_path.parent() {
                fs::create_dir_all(parent).expect("failed to create parent directories");
            }
            fs::write(file_path, b"export default null;\n").expect("failed to write file");
        }
    }

    impl Drop for TempProject {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    fn view(path: &str, app: bool, ssr: bool) -> ViewSpec {
        ViewSpec {
            path: PathBuf::from(path),
            app,
            ssr,
        }
    }

    #[test]
    fn rejects_empty_view_set() {
        let project = TempProject::new();
        let result = normalize_views(vec![], &project.root, Path::new(".gdansk"));
        let err = result.expect_err("expected empty-set validation error");
        assert!(err.to_string().contains("must not be empty"));
    }

    #[test]
    fn rejects_non_jsx_or_tsx_extensions() {
        let project = TempProject::new();
        project.create_file("main.ts");

        let result = normalize_views(
            vec![view("main.ts", false, false)],
            &project.root,
            Path::new(".gdansk"),
        );
        let err = result.expect_err("expected extension validation error");
        assert!(err.to_string().contains(".tsx or .jsx"));
    }

    #[test]
    fn rejects_paths_outside_cwd() {
        let project = TempProject::new();
        let outside = TempProject::new();
        outside.create_file("outside.tsx");

        let result = normalize_views(
            vec![ViewSpec {
                path: outside.root.join("outside.tsx"),
                app: false,
                ssr: false,
            }],
            &project.root,
            Path::new(".gdansk"),
        );
        let err = result.expect_err("expected outside-cwd validation error");
        assert!(err.to_string().contains("inside cwd"));
    }

    #[test]
    fn rejects_output_collisions() {
        let project = TempProject::new();
        project.create_file("a.tsx");
        project.create_file("a.jsx");

        let result = normalize_views(
            vec![view("a.tsx", false, false), view("a.jsx", false, false)],
            &project.root,
            Path::new(".gdansk"),
        );
        let err = result.expect_err("expected output collision validation error");
        assert!(err.to_string().contains("same output"));
    }

    #[test]
    fn preserves_non_app_relative_structure_for_output_mapping() {
        let project = TempProject::new();
        project.create_file("main.tsx");
        project.create_file("home/page.tsx");

        let normalized = normalize_views(
            vec![
                view("main.tsx", false, false),
                view("home/page.tsx", false, false),
            ],
            &project.root,
            Path::new(".gdansk"),
        )
        .expect("expected normalized input set");

        let by_import = normalized
            .into_iter()
            .map(|item| (item.import.clone(), item))
            .collect::<HashMap<_, _>>();

        let main = by_import
            .get("main.tsx")
            .expect("expected main.tsx mapping");
        assert_eq!(main.client_name, "main");
        assert_eq!(format!("{}.js", main.client_name), "main.js");
        assert_eq!(format!("{}.css", main.client_name), "main.css");
        assert_eq!(main.server_name, None);

        let nested = by_import
            .get("home/page.tsx")
            .expect("expected home/page.tsx mapping");
        assert_eq!(nested.client_name, "home/page");
        assert_eq!(format!("{}.js", nested.client_name), "home/page.js");
        assert_eq!(format!("{}.css", nested.client_name), "home/page.css");
        assert_eq!(nested.server_name, None);
    }

    #[test]
    fn app_view_maps_to_per_tool_client_and_server_outputs() {
        let project = TempProject::new();
        project.create_file("apps/get-time/app.tsx");

        let normalized = normalize_views(
            vec![view("apps/get-time/app.tsx", true, true)],
            &project.root,
            Path::new(".gdansk"),
        )
        .expect("expected normalized input set");

        let entry = &normalized[0];
        assert_eq!(entry.client_name, "get-time/client");
        assert_eq!(format!("{}.js", entry.client_name), "get-time/client.js");
        assert_eq!(format!("{}.css", entry.client_name), "get-time/client.css");
        assert_eq!(entry.server_name, Some("get-time/server".to_string()));
        assert_eq!(
            entry.server_name.as_ref().map(|name| format!("{name}.js")),
            Some("get-time/server.js".to_string())
        );
    }

    #[test]
    fn rejects_ssr_when_app_is_false() {
        let project = TempProject::new();
        project.create_file("main.tsx");

        let result = normalize_views(
            vec![view("main.tsx", false, true)],
            &project.root,
            Path::new(".gdansk"),
        );
        let err = result.expect_err("expected ssr validation error");
        assert!(err.to_string().contains("ssr=true"));
    }

    #[test]
    fn rejects_app_view_that_is_not_under_apps() {
        let project = TempProject::new();
        project.create_file("simple/app.tsx");

        let result = normalize_views(
            vec![view("simple/app.tsx", true, false)],
            &project.root,
            Path::new(".gdansk"),
        );
        let err = result.expect_err("expected app path validation error");
        assert!(err.to_string().contains("inside an apps/ directory"));
    }

    #[test]
    fn client_input_fields_rewrite_only_app_views() {
        let project = TempProject::new();
        project.create_file("apps/simple/app.tsx");
        project.create_file("main.tsx");

        let normalized = normalize_views(
            vec![
                view("apps/simple/app.tsx", true, false),
                view("main.tsx", false, false),
            ],
            &project.root,
            Path::new(".gdansk"),
        )
        .expect("expected normalized views");

        let fields = build_client_input_item_fields(&normalized)
            .into_iter()
            .collect::<HashMap<_, _>>();
        assert_eq!(
            fields.get("simple/client"),
            Some(&"apps/simple/app.tsx?gdansk-app-entry".to_string())
        );
        assert_eq!(fields.get("main"), Some(&"main.tsx".to_string()));
    }

    #[test]
    fn server_input_fields_include_only_ssr_views() {
        let project = TempProject::new();
        project.create_file("apps/simple/app.tsx");
        project.create_file("apps/other/app.tsx");

        let normalized = normalize_views(
            vec![
                view("apps/simple/app.tsx", true, true),
                view("apps/other/app.tsx", true, false),
            ],
            &project.root,
            Path::new(".gdansk"),
        )
        .expect("expected normalized views");

        let fields = build_server_input_item_fields(&normalized);
        assert_eq!(fields.len(), 1);
        assert_eq!(fields[0].0, "simple/server");
        assert_eq!(fields[0].1, "apps/simple/app.tsx?gdansk-server-entry");
    }

    #[test]
    fn server_entrypoint_wrapper_imports_runtime_module() {
        let wrapper = server_entrypoint_wrapper_source("apps/simple/app.tsx")
            .expect("expected server wrapper");
        assert!(wrapper.contains(&format!(
            r#"import {{ setSsrHtml }} from "{GDANSK_RUNTIME_SPECIFIER}";"#
        )));
    }

    #[test]
    fn server_entrypoint_wrapper_does_not_call_deno_ops_directly() {
        let wrapper = server_entrypoint_wrapper_source("apps/simple/app.tsx")
            .expect("expected server wrapper");
        assert!(!wrapper.contains("Deno.core.ops.op_gdansk_set_html"));
    }

    #[test]
    fn server_entrypoint_wrapper_does_not_use_global_marker() {
        let wrapper = server_entrypoint_wrapper_source("apps/simple/app.tsx")
            .expect("expected server wrapper");
        assert!(!wrapper.contains("globalThis.__gdansk_html"));
    }
}
