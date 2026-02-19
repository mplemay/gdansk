use std::{
    collections::{HashMap, HashSet},
    fmt,
    path::{Path, PathBuf},
};

#[cfg(not(test))]
use pyo3::{
    exceptions::{PyRuntimeError, PyValueError},
    prelude::*,
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
struct NormalizedInput {
    import: String,
    name: String,
    #[cfg_attr(not(test), allow(dead_code))]
    output_relative_js: PathBuf,
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

#[derive(Debug, Clone, Copy)]
enum EntrypointMode {
    Default,
    App,
    Server,
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

fn entry_import_for_mode(import: &str, entrypoint_mode: EntrypointMode) -> String {
    match entrypoint_mode {
        EntrypointMode::Default => import.to_owned(),
        EntrypointMode::App => format!("{import}{APP_ENTRYPOINT_QUERY}"),
        EntrypointMode::Server => format!("{import}{SERVER_ENTRYPOINT_QUERY}"),
    }
}

fn build_input_item_fields(
    normalized: &[NormalizedInput],
    entrypoint_mode: EntrypointMode,
) -> Vec<(String, String)> {
    normalized
        .iter()
        .map(|item| {
            (
                item.name.clone(),
                entry_import_for_mode(&item.import, entrypoint_mode),
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
fn entrypoint_plugins(entrypoint_mode: EntrypointMode) -> Vec<SharedPluginable> {
    match entrypoint_mode {
        EntrypointMode::Default => vec![],
        EntrypointMode::App => vec![Arc::new(GdanskAppEntrypointPlugin)],
        EntrypointMode::Server => vec![
            Arc::new(GdanskRuntimeModulePlugin),
            Arc::new(GdanskServerEntrypointPlugin),
        ],
    }
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

fn normalize_inputs(
    paths: HashSet<PathBuf>,
    cwd: &Path,
    output_dir: &Path,
) -> Result<Vec<NormalizedInput>, BundleError> {
    if paths.is_empty() {
        return Err(BundleError::validation(
            "`paths` must not be empty; expected at least one .tsx or .jsx file",
        ));
    }

    let cwd_canonical = dunce::simplified(&cwd.canonicalize().map_err(|err| {
        BundleError::runtime(format!(
            "failed to resolve current working directory {}: {err}",
            cwd.display()
        ))
    })?)
    .to_path_buf();

    let mut normalized_inputs = Vec::with_capacity(paths.len());
    let mut output_collisions: HashMap<PathBuf, String> = HashMap::new();

    for provided_path in paths {
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

        let relative_without_ext = relative_path.with_extension("");
        let output_relative_js = relative_without_ext.with_extension("js");

        let import = normalize_relative_for_rolldown(relative_path, "input path")?;
        let name = normalize_relative_for_rolldown(&relative_without_ext, "entry name")?;

        if let Some(previous_input) =
            output_collisions.insert(output_relative_js.clone(), import.clone())
        {
            return Err(BundleError::validation(format!(
                "multiple inputs map to the same output {}: {} and {}",
                output_dir.join(&output_relative_js).display(),
                previous_input,
                import
            )));
        }

        normalized_inputs.push(NormalizedInput {
            import,
            name,
            output_relative_js,
        });
    }

    normalized_inputs.sort_unstable_by(|left, right| left.import.cmp(&right.import));
    Ok(normalized_inputs)
}

#[cfg(not(test))]
fn map_bundle_error(err: BundleError) -> PyErr {
    match err {
        BundleError::Validation(message) => PyValueError::new_err(message),
        BundleError::Runtime(message) => PyRuntimeError::new_err(message),
    }
}

#[cfg(not(test))]
#[pyfunction(
    signature = (
        paths,
        dev = false,
        minify = true,
        output = None,
        cwd = None,
        app_entrypoint_mode = false,
        server_entrypoint_mode = false
    )
)]
#[allow(clippy::too_many_arguments)]
pub(crate) fn bundle(
    py: Python<'_>,
    paths: HashSet<PathBuf>,
    dev: bool,
    minify: bool,
    output: Option<PathBuf>,
    cwd: Option<PathBuf>,
    app_entrypoint_mode: bool,
    server_entrypoint_mode: bool,
) -> PyResult<Bound<'_, PyAny>> {
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

        let normalized = normalize_inputs(paths, &cwd, &output_dir).map_err(map_bundle_error)?;
        let entrypoint_mode = if server_entrypoint_mode {
            EntrypointMode::Server
        } else if app_entrypoint_mode {
            EntrypointMode::App
        } else {
            EntrypointMode::Default
        };
        let input_items = build_input_item_fields(&normalized, entrypoint_mode)
            .into_iter()
            .map(|(name, import)| InputItem {
                name: Some(name),
                import,
            })
            .collect::<Vec<_>>();
        let plugins = entrypoint_plugins(entrypoint_mode);

        let mut options = BundlerOptions {
            input: Some(input_items),
            cwd: Some(cwd),
            dir: Some(output_dir_string),
            entry_filenames: Some("[name].js".to_string().into()),
            css_entry_filenames: Some("[name].css".to_string().into()),
            minify: Some(minify.into()),
            format: if server_entrypoint_mode {
                Some(OutputFormat::Iife)
            } else {
                None
            },
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
        }

        if dev {
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
            Ok(())
        } else {
            let mut bundler = Bundler::with_plugins(options, plugins)
                .map_err(|err| py_runtime_error("failed to initialize Bundler", err))?;
            bundler
                .write()
                .await
                .map_err(|err| py_runtime_error("bundling failed", err))?;
            Ok(())
        }
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

    #[test]
    fn rejects_empty_input_set() {
        let project = TempProject::new();
        let result = normalize_inputs(HashSet::new(), &project.root, Path::new(".gdansk"));
        let err = result.expect_err("expected empty-set validation error");
        assert!(err.to_string().contains("must not be empty"));
    }

    #[test]
    fn rejects_non_jsx_or_tsx_extensions() {
        let project = TempProject::new();
        project.create_file("main.ts");

        let paths = HashSet::from([PathBuf::from("main.ts")]);
        let result = normalize_inputs(paths, &project.root, Path::new(".gdansk"));
        let err = result.expect_err("expected extension validation error");
        assert!(err.to_string().contains(".tsx or .jsx"));
    }

    #[test]
    fn rejects_paths_outside_cwd() {
        let project = TempProject::new();
        let outside = TempProject::new();
        outside.create_file("outside.tsx");

        let paths = HashSet::from([outside.root.join("outside.tsx")]);
        let result = normalize_inputs(paths, &project.root, Path::new(".gdansk"));
        let err = result.expect_err("expected outside-cwd validation error");
        assert!(err.to_string().contains("inside cwd"));
    }

    #[test]
    fn rejects_output_collisions() {
        let project = TempProject::new();
        project.create_file("a.tsx");
        project.create_file("a.jsx");

        let paths = HashSet::from([PathBuf::from("a.tsx"), PathBuf::from("a.jsx")]);
        let result = normalize_inputs(paths, &project.root, Path::new(".gdansk"));
        let err = result.expect_err("expected output collision validation error");
        assert!(err.to_string().contains("same output"));
    }

    #[test]
    fn preserves_relative_structure_for_output_mapping() {
        let project = TempProject::new();
        project.create_file("main.tsx");
        project.create_file("home/page.tsx");

        let paths = HashSet::from([PathBuf::from("main.tsx"), PathBuf::from("home/page.tsx")]);
        let normalized = normalize_inputs(paths, &project.root, Path::new(".gdansk"))
            .expect("expected normalized input set");

        let by_import = normalized
            .into_iter()
            .map(|item| (item.import.clone(), item))
            .collect::<HashMap<_, _>>();

        let main = by_import
            .get("main.tsx")
            .expect("expected main.tsx mapping");
        assert_eq!(main.name, "main");
        assert_eq!(main.output_relative_js, PathBuf::from("main.js"));

        let nested = by_import
            .get("home/page.tsx")
            .expect("expected home/page.tsx mapping");
        assert_eq!(nested.name, "home/page");
        assert_eq!(nested.output_relative_js, PathBuf::from("home/page.js"));
    }

    #[test]
    fn app_entrypoint_mode_rewrites_import_and_preserves_name() {
        let project = TempProject::new();
        project.create_file("apps/simple/app.tsx");

        let paths = HashSet::from([PathBuf::from("apps/simple/app.tsx")]);
        let normalized = normalize_inputs(paths, &project.root, Path::new(".gdansk"))
            .expect("expected normalized input set");

        let input_fields = build_input_item_fields(&normalized, EntrypointMode::App);
        assert_eq!(input_fields.len(), 1);
        assert_eq!(input_fields[0].0, "apps/simple/app");
        assert_eq!(input_fields[0].1, "apps/simple/app.tsx?gdansk-app-entry");
    }

    #[test]
    fn default_mode_keeps_original_entry_import() {
        let project = TempProject::new();
        project.create_file("apps/simple/app.tsx");

        let paths = HashSet::from([PathBuf::from("apps/simple/app.tsx")]);
        let normalized = normalize_inputs(paths, &project.root, Path::new(".gdansk"))
            .expect("expected normalized input set");

        let input_fields = build_input_item_fields(&normalized, EntrypointMode::Default);
        assert_eq!(input_fields.len(), 1);
        assert_eq!(input_fields[0].0, "apps/simple/app");
        assert_eq!(input_fields[0].1, "apps/simple/app.tsx");
    }

    #[test]
    fn server_entrypoint_mode_rewrites_import_and_preserves_name() {
        let project = TempProject::new();
        project.create_file("apps/simple/app.tsx");

        let paths = HashSet::from([PathBuf::from("apps/simple/app.tsx")]);
        let normalized = normalize_inputs(paths, &project.root, Path::new(".gdansk"))
            .expect("expected normalized input set");

        let input_fields = build_input_item_fields(&normalized, EntrypointMode::Server);
        assert_eq!(input_fields.len(), 1);
        assert_eq!(input_fields[0].0, "apps/simple/app");
        assert_eq!(input_fields[0].1, "apps/simple/app.tsx?gdansk-server-entry");
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
        assert!(!wrapper.contains("Deno.core.ops.op_gdansk_set_ssr_html"));
    }

    #[test]
    fn server_entrypoint_wrapper_does_not_use_global_marker() {
        let wrapper = server_entrypoint_wrapper_source("apps/simple/app.tsx")
            .expect("expected server wrapper");
        assert!(!wrapper.contains("globalThis.__gdansk_ssr_html"));
    }
}
