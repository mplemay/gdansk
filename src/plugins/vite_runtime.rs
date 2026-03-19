#![cfg_attr(test, allow(dead_code))]

use std::{
    collections::BTreeSet,
    ffi::OsStr,
    fs,
    path::{Component, Path, PathBuf},
    rc::Rc,
    sync::Arc,
};

use deno_core::{
    JsRuntime, ModuleLoadOptions, ModuleLoadReferrer, ModuleLoadResponse, ModuleLoader,
    ModuleSource, ModuleSourceCode, ModuleSpecifier, ModuleType, OpState, PollEventLoopOptions,
    ResolutionKind, RuntimeOptions, op2,
    serde_json::{self, Value},
    v8,
};
use deno_error::JsErrorBox;
use oxc_resolver::{ResolveOptions, Resolver};
use serde::{Deserialize, Serialize};
use url::Url;

use super::vite::VitePluginSpec;

const BOOTSTRAP_SPECIFIER: &str = "gdansk:vite-runtime-bootstrap";
const NODE_FS_SPECIFIER: &str = "node:fs";
const NODE_FS_PROMISES_SPECIFIER: &str = "node:fs/promises";
const NODE_MODULE_SPECIFIER: &str = "node:module";
const NODE_PATH_SPECIFIER: &str = "node:path";
const NODE_URL_SPECIFIER: &str = "node:url";
const GDANSK_FS_SPECIFIER: &str = "gdansk:fs";
const GDANSK_FS_PROMISES_SPECIFIER: &str = "gdansk:fs/promises";
const GDANSK_MODULE_SPECIFIER: &str = "gdansk:module";
const GDANSK_JITI_SHIM_SPECIFIER: &str = "gdansk:jiti";
const GDANSK_LIGHTNINGCSS_SHIM_SPECIFIER: &str = "gdansk:lightningcss";
const GDANSK_PATH_SPECIFIER: &str = "gdansk:path";
const GDANSK_TAILWIND_VITE_SHIM_SPECIFIER: &str = "gdansk:tailwindcss-vite";
const GDANSK_URL_SPECIFIER: &str = "gdansk:url";
const GDANSK_VITE_SHIM_SPECIFIER: &str = "gdansk:vite";

fn normalize_supported_node_builtin(specifier: &str) -> Option<&'static str> {
    match specifier {
        "fs" | NODE_FS_SPECIFIER => Some(NODE_FS_SPECIFIER),
        "fs/promises" | NODE_FS_PROMISES_SPECIFIER => Some(NODE_FS_PROMISES_SPECIFIER),
        "module" | NODE_MODULE_SPECIFIER => Some(NODE_MODULE_SPECIFIER),
        "path" | NODE_PATH_SPECIFIER => Some(NODE_PATH_SPECIFIER),
        "url" | NODE_URL_SPECIFIER => Some(NODE_URL_SPECIFIER),
        _ => None,
    }
}

fn builtin_module_specifier(specifier: &str) -> Option<&'static str> {
    match normalize_supported_node_builtin(specifier) {
        Some(NODE_FS_SPECIFIER) => Some(GDANSK_FS_SPECIFIER),
        Some(NODE_FS_PROMISES_SPECIFIER) => Some(GDANSK_FS_PROMISES_SPECIFIER),
        Some(NODE_MODULE_SPECIFIER) => Some(GDANSK_MODULE_SPECIFIER),
        Some(NODE_PATH_SPECIFIER) => Some(GDANSK_PATH_SPECIFIER),
        Some(NODE_URL_SPECIFIER) => Some(GDANSK_URL_SPECIFIER),
        _ => None,
    }
}

fn builtin_module_source(specifier: &str) -> Option<&'static str> {
    match specifier {
        GDANSK_FS_SPECIFIER => Some(include_str!("vite_fs.js")),
        GDANSK_FS_PROMISES_SPECIFIER => Some(include_str!("vite.js")),
        GDANSK_JITI_SHIM_SPECIFIER => Some(include_str!("vite_jiti.js")),
        GDANSK_LIGHTNINGCSS_SHIM_SPECIFIER => Some(include_str!("vite_lightningcss.js")),
        GDANSK_MODULE_SPECIFIER => Some(include_str!("vite_node_module.js")),
        GDANSK_PATH_SPECIFIER => Some(include_str!("vite_path.js")),
        GDANSK_TAILWIND_VITE_SHIM_SPECIFIER => Some(include_str!("vite_tailwind_vite.js")),
        GDANSK_URL_SPECIFIER => Some(include_str!("vite_url.js")),
        GDANSK_VITE_SHIM_SPECIFIER => Some(include_str!("vite_module.js")),
        _ => None,
    }
}

#[derive(Debug, Clone)]
pub(super) struct PluginAssetInput {
    pub(super) filename: String,
    pub(super) path: String,
    pub(super) code: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(super) struct PluginAssetOutput {
    pub(super) filename: String,
    pub(super) code: String,
}

#[derive(Debug, Deserialize)]
pub(super) struct PluginRunResult {
    pub(super) assets: Vec<PluginAssetOutput>,
    #[serde(rename = "watchFiles", default)]
    pub(super) watch_files: Vec<String>,
}

#[derive(Debug, Serialize)]
struct BootstrapContext {
    pages: String,
}

#[derive(Debug, Deserialize)]
struct TransformHookResult {
    code: Option<String>,
    #[serde(rename = "watchFiles", default)]
    watch_files: Vec<String>,
}

#[derive(Debug)]
struct ViteRuntimeState {
    shared: Arc<ViteRuntimeShared>,
}

#[derive(Debug)]
struct ViteRuntimeShared {
    pages: PathBuf,
    js_resolver: Resolver,
}

impl ViteRuntimeShared {
    fn new(pages: &Path) -> Self {
        let js_resolver = Resolver::new(
            ResolveOptions::default().with_condition_names(&["node", "import", "default"]),
        );
        Self {
            pages: pages.to_path_buf(),
            js_resolver,
        }
    }

    fn resolve_input_path(&self, input: &str) -> Result<PathBuf, JsErrorBox> {
        if input.starts_with("file://") {
            let specifier = ModuleSpecifier::parse(input)
                .map_err(|err| JsErrorBox::generic(err.to_string()))?;
            return specifier
                .to_file_path()
                .map_err(|_| JsErrorBox::generic(format!("unsupported file URL: {input}")));
        }

        let path = Path::new(input);
        if path.is_absolute() {
            return Ok(path.to_path_buf());
        }

        Ok(self.pages.join(path))
    }

    fn normalize_watch_file(&self, file: &str) -> Result<String, JsErrorBox> {
        let path = self.resolve_input_path(file)?;
        Ok(dunce::simplified(&path).to_string_lossy().into_owned())
    }

    fn resolve_js_path(
        &self,
        specifier: &str,
        importer: Option<&str>,
    ) -> Result<String, JsErrorBox> {
        if let Some(specifier) = normalize_supported_node_builtin(specifier) {
            return Ok(specifier.to_owned());
        }

        if specifier.starts_with("node:") {
            return Err(unsupported_node_builtin(specifier));
        }

        let resolved = self.resolve_js_module_specifier(specifier, importer, false)?;
        if resolved.scheme() == "node" {
            return Ok(resolved.to_string());
        }

        let path = resolved.to_file_path().map_err(|_| {
            JsErrorBox::generic(format!("unsupported module specifier: {resolved}"))
        })?;
        Ok(dunce::simplified(&path).to_string_lossy().into_owned())
    }

    fn resolve_css_path(
        &self,
        specifier: &str,
        importer: Option<&str>,
    ) -> Result<String, JsErrorBox> {
        let importer_dir = importer
            .map(|value| self.resolve_input_path(value))
            .transpose()?
            .map(|path| {
                if path.is_dir() {
                    path
                } else {
                    path.parent().unwrap_or(path.as_path()).to_path_buf()
                }
            })
            .unwrap_or_else(|| self.pages.clone());

        let resolved = resolve_css_import_path(specifier, &importer_dir, &self.pages)?;
        Ok(resolved.to_string_lossy().into_owned())
    }

    fn resolve_js_module_specifier(
        &self,
        specifier: &str,
        importer: Option<&str>,
        from_loader: bool,
    ) -> Result<ModuleSpecifier, JsErrorBox> {
        if specifier == "jiti" {
            return ModuleSpecifier::parse(GDANSK_JITI_SHIM_SPECIFIER)
                .map_err(|err| JsErrorBox::generic(err.to_string()));
        }

        // Tailwind's published Vite plugin assumes a fuller Node runtime than
        // the embedded loader provides, so we route it through a focused shim.
        if specifier == "@tailwindcss/vite" {
            return ModuleSpecifier::parse(GDANSK_TAILWIND_VITE_SHIM_SPECIFIER)
                .map_err(|err| JsErrorBox::generic(err.to_string()));
        }

        if specifier == "lightningcss" {
            return ModuleSpecifier::parse(GDANSK_LIGHTNINGCSS_SHIM_SPECIFIER)
                .map_err(|err| JsErrorBox::generic(err.to_string()));
        }

        if specifier == "vite" {
            return ModuleSpecifier::parse(GDANSK_VITE_SHIM_SPECIFIER)
                .map_err(|err| JsErrorBox::generic(err.to_string()));
        }

        if let Some(specifier) = builtin_module_specifier(specifier) {
            return ModuleSpecifier::parse(specifier)
                .map_err(|err| JsErrorBox::generic(err.to_string()));
        }

        if specifier.starts_with("node:") {
            return Err(unsupported_node_builtin(specifier));
        }

        if specifier.starts_with("file://") {
            return ModuleSpecifier::parse(specifier)
                .map_err(|err| JsErrorBox::generic(err.to_string()));
        }

        let path = Path::new(specifier);
        if path.is_absolute() {
            let resolved = canonicalize_existing_file(path)?;
            return path_to_module_specifier(&resolved);
        }

        if is_relative_specifier(specifier) {
            let base_dir = importer
                .filter(|referrer| *referrer != BOOTSTRAP_SPECIFIER)
                .map(|referrer| {
                    self.resolve_input_path(referrer).map(|path| {
                        if path.is_dir() {
                            path
                        } else {
                            path.parent().unwrap_or(path.as_path()).to_path_buf()
                        }
                    })
                })
                .transpose()?
                .unwrap_or_else(|| self.pages.clone());
            let resolved = canonicalize_existing_file(&base_dir.join(specifier))?;
            return path_to_module_specifier(&resolved);
        }

        let resolution = match importer.filter(|referrer| *referrer != BOOTSTRAP_SPECIFIER) {
            Some(importer) => self
                .js_resolver
                .resolve_file(self.resolve_input_path(importer)?, specifier),
            None => self.js_resolver.resolve(&self.pages, specifier),
        }
        .map_err(|err| JsErrorBox::generic(err.to_string()))?;

        let resolved = resolution.path().to_path_buf();
        if from_loader && !resolved.is_file() {
            return Err(JsErrorBox::generic(format!(
                "resolved module is not a file: {}",
                resolved.display()
            )));
        }

        path_to_module_specifier(&resolved)
    }
}

struct ViteModuleLoader {
    shared: Arc<ViteRuntimeShared>,
}

impl ModuleLoader for ViteModuleLoader {
    fn resolve(
        &self,
        specifier: &str,
        referrer: &str,
        _kind: ResolutionKind,
    ) -> Result<ModuleSpecifier, JsErrorBox> {
        self.shared
            .resolve_js_module_specifier(specifier, Some(referrer), true)
    }

    fn load(
        &self,
        module_specifier: &ModuleSpecifier,
        _maybe_referrer: Option<&ModuleLoadReferrer>,
        _options: ModuleLoadOptions,
    ) -> ModuleLoadResponse {
        let result = (|| {
            if let Some(code) = builtin_module_source(module_specifier.as_str()) {
                return Ok(ModuleSource::new(
                    ModuleType::JavaScript,
                    ModuleSourceCode::String(code.to_owned().into()),
                    module_specifier,
                    None,
                ));
            }

            if module_specifier.scheme() == "node" {
                return Err(unsupported_node_builtin(module_specifier.as_str()));
            }

            let path = module_specifier.to_file_path().map_err(|_| {
                JsErrorBox::generic(format!("unsupported module specifier: {module_specifier}"))
            })?;
            let code =
                fs::read_to_string(&path).map_err(|err| JsErrorBox::generic(err.to_string()))?;
            let module_type = if path.extension() == Some(OsStr::new("json")) {
                ModuleType::Json
            } else {
                ModuleType::JavaScript
            };

            Ok(ModuleSource::new(
                module_type,
                ModuleSourceCode::String(code.into()),
                module_specifier,
                None,
            ))
        })();

        ModuleLoadResponse::Sync(result)
    }
}

#[derive(Debug, Serialize)]
struct StatResult {
    #[serde(rename = "mtimeMs")]
    mtime_ms: f64,
    #[serde(rename = "isDirectory")]
    is_directory: bool,
    #[serde(rename = "isFile")]
    is_file: bool,
}

#[derive(Debug, Serialize)]
struct ReadDirEntryResult {
    name: String,
    #[serde(rename = "isDirectory")]
    is_directory: bool,
    #[serde(rename = "isFile")]
    is_file: bool,
}

#[op2]
#[string]
fn op_gdansk_vite_read_text_file(
    state: &mut OpState,
    #[string] path: String,
    #[string] encoding: Option<String>,
) -> Result<String, JsErrorBox> {
    if let Some(encoding) = encoding.as_deref() {
        let normalized = encoding.to_ascii_lowercase();
        if normalized != "utf8" && normalized != "utf-8" {
            return Err(JsErrorBox::generic(format!(
                "unsupported file encoding: {encoding}"
            )));
        }
    }

    let shared = state.borrow::<ViteRuntimeState>().shared.clone();
    let path = shared.resolve_input_path(&path)?;
    fs::read_to_string(path).map_err(|err| JsErrorBox::generic(err.to_string()))
}

#[op2]
#[string]
fn op_gdansk_vite_realpath_sync(
    state: &mut OpState,
    #[string] path: String,
) -> Result<String, JsErrorBox> {
    let shared = state.borrow::<ViteRuntimeState>().shared.clone();
    let path = shared.resolve_input_path(&path)?;
    canonicalize_existing_file(&path).map(|path| path.to_string_lossy().into_owned())
}

#[op2]
#[string]
fn op_gdansk_vite_stat(state: &mut OpState, #[string] path: String) -> Result<String, JsErrorBox> {
    let shared = state.borrow::<ViteRuntimeState>().shared.clone();
    let path = shared.resolve_input_path(&path)?;
    let metadata = fs::metadata(path).map_err(|err| JsErrorBox::generic(err.to_string()))?;
    let mtime_ms = metadata
        .modified()
        .ok()
        .and_then(|value| value.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|value| value.as_secs_f64() * 1000.0)
        .unwrap_or(0.0);
    serde_json::to_string(&StatResult {
        mtime_ms,
        is_directory: metadata.is_dir(),
        is_file: metadata.is_file(),
    })
    .map_err(|err| JsErrorBox::generic(err.to_string()))
}

#[op2]
#[string]
fn op_gdansk_vite_read_dir(
    state: &mut OpState,
    #[string] path: String,
) -> Result<String, JsErrorBox> {
    let shared = state.borrow::<ViteRuntimeState>().shared.clone();
    let path = shared.resolve_input_path(&path)?;
    let mut entries = Vec::new();

    for entry in fs::read_dir(path).map_err(|err| JsErrorBox::generic(err.to_string()))? {
        let entry = entry.map_err(|err| JsErrorBox::generic(err.to_string()))?;
        let file_type = entry
            .file_type()
            .map_err(|err| JsErrorBox::generic(err.to_string()))?;
        entries.push(ReadDirEntryResult {
            name: entry.file_name().to_string_lossy().into_owned(),
            is_directory: file_type.is_dir(),
            is_file: file_type.is_file(),
        });
    }

    serde_json::to_string(&entries).map_err(|err| JsErrorBox::generic(err.to_string()))
}

#[op2]
#[string]
fn op_gdansk_vite_resolve(
    state: &mut OpState,
    #[string] specifier: String,
    #[string] importer: Option<String>,
    #[string] resolver_kind: String,
) -> Result<String, JsErrorBox> {
    let shared = state.borrow::<ViteRuntimeState>().shared.clone();
    match resolver_kind.as_str() {
        "css" => shared.resolve_css_path(&specifier, importer.as_deref()),
        "js" => shared.resolve_js_path(&specifier, importer.as_deref()),
        _ => Err(JsErrorBox::generic(format!(
            "unsupported resolver kind: {resolver_kind}"
        ))),
    }
}

#[op2]
#[string]
fn op_gdansk_vite_normalize_watch_file(
    state: &mut OpState,
    #[string] file: String,
) -> Result<String, JsErrorBox> {
    let shared = state.borrow::<ViteRuntimeState>().shared.clone();
    shared.normalize_watch_file(&file)
}

#[op2]
#[string]
fn op_gdansk_vite_path_basename(#[string] path: String) -> String {
    basename_string(&path)
}

#[op2]
#[string]
fn op_gdansk_vite_path_dirname(#[string] path: String) -> String {
    dirname_string(&path)
}

#[op2]
#[string]
fn op_gdansk_vite_path_extname(#[string] path: String) -> String {
    extname_string(&path)
}

#[op2]
#[string]
fn op_gdansk_vite_path_relative(
    #[string] from: String,
    #[string] to: String,
) -> Result<String, JsErrorBox> {
    diff_paths(Path::new(&to), Path::new(&from)).map(|path| {
        let path = path.to_string_lossy();
        if path == "." {
            String::new()
        } else {
            path.into_owned()
        }
    })
}

#[op2]
#[string]
fn op_gdansk_vite_path_resolve(#[string] paths: String) -> Result<String, JsErrorBox> {
    resolve_string_path_segments(&paths)
}

#[op2]
#[string]
fn op_gdansk_vite_path_posix_join(#[string] paths: String) -> Result<String, JsErrorBox> {
    join_posix_segments(&paths)
}

#[op2]
#[string]
fn op_gdansk_vite_file_url_to_path(#[string] url: String) -> Result<String, JsErrorBox> {
    Url::parse(&url)
        .map_err(|err| JsErrorBox::generic(err.to_string()))?
        .to_file_path()
        .map_err(|_| JsErrorBox::generic(format!("unsupported file URL: {url}")))
        .map(|path| path.to_string_lossy().into_owned())
}

#[op2]
#[string]
fn op_gdansk_vite_path_to_file_url(#[string] path: String) -> Result<String, JsErrorBox> {
    let path = absolute_lexical_path(Path::new(&path))?;
    Url::from_file_path(&path)
        .map_err(|_| JsErrorBox::generic(format!("failed to resolve path {}", path.display())))
        .map(|url| url.to_string())
}

deno_core::extension!(
    gdansk_vite_plugin_ext,
    ops = [
        op_gdansk_vite_read_text_file,
        op_gdansk_vite_read_dir,
        op_gdansk_vite_realpath_sync,
        op_gdansk_vite_stat,
        op_gdansk_vite_resolve,
        op_gdansk_vite_normalize_watch_file,
        op_gdansk_vite_path_basename,
        op_gdansk_vite_path_dirname,
        op_gdansk_vite_path_extname,
        op_gdansk_vite_path_relative,
        op_gdansk_vite_path_resolve,
        op_gdansk_vite_path_posix_join,
        op_gdansk_vite_file_url_to_path,
        op_gdansk_vite_path_to_file_url,
    ],
    esm_entry_point = BOOTSTRAP_SPECIFIER,
    esm = [
        dir "src/plugins",
        "gdansk:vite-runtime-bootstrap" = "vite_runtime.js",
    ],
    options = {
        shared: Arc<ViteRuntimeShared>,
    },
    state = |state, options| {
        state.put(ViteRuntimeState {
            shared: options.shared,
        });
    }
);

struct EmbeddedViteRuntime {
    runtime: JsRuntime,
}

impl EmbeddedViteRuntime {
    fn new(pages: &Path) -> Self {
        let shared = Arc::new(ViteRuntimeShared::new(pages));
        let module_loader = Rc::new(ViteModuleLoader {
            shared: shared.clone(),
        });
        let runtime = JsRuntime::new(RuntimeOptions {
            module_loader: Some(module_loader),
            extensions: vec![gdansk_vite_plugin_ext::init(shared)],
            ..Default::default()
        });

        Self { runtime }
    }

    async fn load_plugins(
        &mut self,
        specs: &[VitePluginSpec],
        pages: &Path,
    ) -> Result<usize, std::io::Error> {
        let specs_json = serde_json::to_string(specs).map_err(std::io::Error::other)?;
        let context_json = serde_json::to_string(&BootstrapContext {
            pages: pages.to_string_lossy().into_owned(),
        })
        .map_err(std::io::Error::other)?;
        self.execute_json(
            "<gdansk-vite-load-plugins>",
            format!("globalThis.__gdansk_vite_runtime.loadPlugins({specs_json}, {context_json})"),
        )
        .await
    }

    async fn transform_plugin(
        &mut self,
        index: usize,
        code: &str,
        id: &str,
    ) -> Result<Option<TransformHookResult>, std::io::Error> {
        let code_json = serde_json::to_string(code).map_err(std::io::Error::other)?;
        let id_json = serde_json::to_string(id).map_err(std::io::Error::other)?;
        self.execute_json(
            "<gdansk-vite-transform-plugin>",
            format!(
                "globalThis.__gdansk_vite_runtime.transformPlugin({index}, {code_json}, {id_json})"
            ),
        )
        .await
    }

    async fn execute_json<T>(&mut self, name: &str, source: String) -> Result<T, std::io::Error>
    where
        T: for<'de> Deserialize<'de>,
    {
        let output = self
            .runtime
            .execute_script(name.to_owned(), source)
            .map_err(execution_error)?;
        let resolve = self.runtime.resolve(output);
        let output = self
            .runtime
            .with_event_loop_promise(resolve, PollEventLoopOptions::default())
            .await
            .map_err(execution_error)?;
        let value = read_json_value(&mut self.runtime, output)?;
        serde_json::from_value(value).map_err(std::io::Error::other)
    }
}

pub(super) fn run_embedded_vite_plugins(
    specs: &[VitePluginSpec],
    pages: &Path,
    assets: Vec<PluginAssetInput>,
) -> Result<PluginRunResult, std::io::Error> {
    #[cfg(test)]
    let _guard = crate::test_support::js_runtime_lock()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(execution_error)?;
    runtime.block_on(async move {
        let mut embedded = EmbeddedViteRuntime::new(pages);
        let plugin_count = embedded.load_plugins(specs, pages).await?;
        if plugin_count == 0 || assets.is_empty() {
            return Ok(PluginRunResult {
                assets: Vec::new(),
                watch_files: Vec::new(),
            });
        }

        let mut changed_assets = Vec::new();
        let mut watch_files = BTreeSet::new();
        for asset in assets {
            let mut current = asset.code;
            let mut changed = false;

            for plugin_index in 0..plugin_count {
                let Some(result) = embedded
                    .transform_plugin(plugin_index, &current, &asset.path)
                    .await?
                else {
                    continue;
                };

                watch_files.extend(result.watch_files);
                if let Some(next_code) = result.code
                    && next_code != current
                {
                    current = next_code;
                    changed = true;
                }
            }

            if changed {
                changed_assets.push(PluginAssetOutput {
                    filename: asset.filename,
                    code: current,
                });
            }
        }

        Ok(PluginRunResult {
            assets: changed_assets,
            watch_files: watch_files.into_iter().collect(),
        })
    })
}

fn execution_error(err: impl std::fmt::Debug) -> std::io::Error {
    std::io::Error::other(format!("Execution error: {err:?}"))
}

fn read_json_value(
    runtime: &mut JsRuntime,
    output: v8::Global<v8::Value>,
) -> Result<Value, std::io::Error> {
    deno_core::scope!(scope, runtime);
    let local = v8::Local::new(scope, output);
    if local.is_number() {
        let Some(number) = local.number_value(scope) else {
            return Err(std::io::Error::other(
                "Cannot deserialize value: unsupported JavaScript value",
            ));
        };
        if !number.is_finite() {
            return Err(std::io::Error::other(
                "Cannot deserialize value: unsupported JavaScript value",
            ));
        }
    }
    if local.is_undefined()
        || local.is_function()
        || local.is_symbol()
        || local.is_big_int()
        || local.is_promise()
    {
        return Err(std::io::Error::other(
            "Cannot deserialize value: unsupported JavaScript value",
        ));
    }
    deno_core::serde_v8::from_v8::<Value>(scope, local).map_err(std::io::Error::other)
}

fn is_relative_specifier(specifier: &str) -> bool {
    specifier.starts_with("./") || specifier.starts_with("../")
}

fn canonicalize_existing_file(path: &Path) -> Result<PathBuf, JsErrorBox> {
    path.canonicalize()
        .map(|path| dunce::simplified(&path).to_path_buf())
        .map_err(|err| JsErrorBox::generic(err.to_string()))
}

fn path_to_module_specifier(path: &Path) -> Result<ModuleSpecifier, JsErrorBox> {
    let specifier = Url::from_file_path(path)
        .map_err(|_| JsErrorBox::generic(format!("failed to resolve path {}", path.display())))?
        .to_string();
    ModuleSpecifier::parse(&specifier).map_err(|err| JsErrorBox::generic(err.to_string()))
}

fn current_dir() -> Result<PathBuf, JsErrorBox> {
    std::env::current_dir().map_err(|err| JsErrorBox::generic(err.to_string()))
}

fn normalize_path(path: &Path) -> PathBuf {
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                if matches!(
                    normalized.components().next_back(),
                    Some(Component::Normal(_))
                ) {
                    normalized.pop();
                } else if !normalized.has_root() {
                    normalized.push("..");
                }
            }
            Component::Prefix(_) | Component::RootDir | Component::Normal(_) => {
                normalized.push(component.as_os_str());
            }
        }
    }

    if normalized.as_os_str().is_empty() {
        PathBuf::from(".")
    } else {
        normalized
    }
}

fn absolute_lexical_path(path: &Path) -> Result<PathBuf, JsErrorBox> {
    if path.is_absolute() {
        return Ok(normalize_path(path));
    }

    Ok(normalize_path(&current_dir()?.join(path)))
}

fn diff_paths(path: &Path, base: &Path) -> Result<PathBuf, JsErrorBox> {
    let path = absolute_lexical_path(path)?;
    let base = absolute_lexical_path(base)?;

    if path.is_absolute()
        && base.is_absolute()
        && path.components().next() != base.components().next()
    {
        return Ok(path);
    }

    let path_components = path.components().collect::<Vec<_>>();
    let base_components = base.components().collect::<Vec<_>>();

    let common_prefix = path_components
        .iter()
        .zip(base_components.iter())
        .take_while(|(left, right)| left == right)
        .count();

    let mut relative = PathBuf::new();
    for component in &base_components[common_prefix..] {
        if matches!(component, Component::Normal(_)) {
            relative.push("..");
        }
    }
    for component in &path_components[common_prefix..] {
        relative.push(component.as_os_str());
    }

    if relative.as_os_str().is_empty() {
        Ok(PathBuf::from("."))
    } else {
        Ok(relative)
    }
}

fn basename_string(path: &str) -> String {
    Path::new(path)
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or_default()
        .to_owned()
}

fn dirname_string(path: &str) -> String {
    let path = Path::new(path);
    if let Some(parent) = path.parent() {
        let parent = parent.to_string_lossy();
        if parent.is_empty() {
            ".".to_owned()
        } else {
            parent.into_owned()
        }
    } else if path.has_root() {
        path.to_string_lossy().into_owned()
    } else {
        ".".to_owned()
    }
}

fn extname_string(path: &str) -> String {
    let Some(file_name) = Path::new(path).file_name().and_then(|name| name.to_str()) else {
        return String::new();
    };
    let Some((stem, extension)) = file_name.rsplit_once('.') else {
        return String::new();
    };
    if stem.is_empty() {
        return String::new();
    }
    format!(".{extension}")
}

fn parse_string_array(input: &str) -> Result<Vec<String>, JsErrorBox> {
    serde_json::from_str(input).map_err(|err| JsErrorBox::generic(err.to_string()))
}

fn resolve_string_path_segments(input: &str) -> Result<String, JsErrorBox> {
    let segments = parse_string_array(input)?;
    let mut resolved = current_dir()?;
    for segment in segments {
        if segment.is_empty() {
            continue;
        }

        let path = Path::new(&segment);
        if path.is_absolute() {
            resolved = path.to_path_buf();
        } else {
            resolved.push(path);
        }
    }

    Ok(normalize_path(&resolved).to_string_lossy().into_owned())
}

fn join_posix_segments(input: &str) -> Result<String, JsErrorBox> {
    let segments = parse_string_array(input)?;
    let mut absolute = false;
    let mut parts = Vec::new();

    for segment in segments {
        if segment.is_empty() {
            continue;
        }
        if segment.starts_with('/') {
            absolute = true;
            parts.clear();
        }

        for part in segment.split('/') {
            match part {
                "" | "." => {}
                ".." => {
                    if parts.last().is_some_and(|last| last != "..") {
                        parts.pop();
                    } else if !absolute {
                        parts.push("..".to_owned());
                    }
                }
                _ => parts.push(part.to_owned()),
            }
        }
    }

    if parts.is_empty() {
        return Ok(if absolute {
            "/".to_owned()
        } else {
            ".".to_owned()
        });
    }

    let joined = parts.join("/");
    Ok(if absolute {
        format!("/{joined}")
    } else {
        joined
    })
}

fn unsupported_node_builtin(specifier: &str) -> JsErrorBox {
    JsErrorBox::generic(format!("unsupported node builtin module: {specifier}"))
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct PackageSpecifierParts {
    package_name: String,
    subpath: Option<String>,
}

fn split_package_specifier(specifier: &str) -> Option<PackageSpecifierParts> {
    if specifier.starts_with("./")
        || specifier.starts_with("../")
        || Path::new(specifier).is_absolute()
    {
        return None;
    }

    if let Some(rest) = specifier.strip_prefix('@') {
        let (scope, rest) = rest.split_once('/')?;
        let (name, subpath) = match rest.split_once('/') {
            Some((name, subpath)) => (name, Some(subpath.to_owned())),
            None => (rest, None),
        };
        return Some(PackageSpecifierParts {
            package_name: format!("@{scope}/{name}"),
            subpath,
        });
    }

    let (package_name, subpath) = match specifier.split_once('/') {
        Some((package_name, subpath)) => (package_name.to_owned(), Some(subpath.to_owned())),
        None => (specifier.to_owned(), None),
    };
    Some(PackageSpecifierParts {
        package_name,
        subpath,
    })
}

fn find_node_modules_package_dir(
    package_name: &str,
    importer_dir: &Path,
    root_dir: &Path,
) -> Option<PathBuf> {
    let mut current = importer_dir;
    loop {
        let candidate = current.join("node_modules").join(package_name);
        if candidate.is_dir() {
            return Some(candidate);
        }

        if current == root_dir {
            break;
        }

        let parent = current.parent()?;
        if parent == current {
            break;
        }
        current = parent;
    }

    None
}

fn resolve_package_style_export(
    package_dir: &Path,
    specifier: &str,
    subpath: Option<&str>,
) -> Result<PathBuf, JsErrorBox> {
    let package_json_path = package_dir.join("package.json");
    let package_json = fs::read_to_string(&package_json_path)
        .map_err(|err| JsErrorBox::generic(err.to_string()))?;
    let package_json: Value =
        serde_json::from_str(&package_json).map_err(|err| JsErrorBox::generic(err.to_string()))?;
    let export_key = subpath
        .map(|subpath| format!("./{subpath}"))
        .unwrap_or_else(|| ".".to_owned());
    let export_entry = package_json
        .get("exports")
        .and_then(Value::as_object)
        .and_then(|exports| exports.get(&export_key))
        .ok_or_else(|| {
            JsErrorBox::generic(format!(
                "package \"{specifier}\" does not define exports[\"{export_key}\"]"
            ))
        })?;

    let style_path = match export_entry {
        Value::String(path) => Some(path.to_owned()),
        Value::Object(entry) => entry
            .get("style")
            .and_then(Value::as_str)
            .map(str::to_owned)
            .or_else(|| {
                package_json
                    .get("style")
                    .and_then(Value::as_str)
                    .map(str::to_owned)
            }),
        _ => None,
    }
    .ok_or_else(|| {
        JsErrorBox::generic(format!(
            "package \"{specifier}\" does not define a style export for \"{export_key}\""
        ))
    })?;

    canonicalize_existing_file(&package_dir.join(style_path))
}

fn resolve_css_import_path(
    specifier: &str,
    importer_dir: &Path,
    root_dir: &Path,
) -> Result<PathBuf, JsErrorBox> {
    if is_relative_specifier(specifier) {
        return canonicalize_existing_file(&importer_dir.join(specifier));
    }

    let path = Path::new(specifier);
    if path.is_absolute() {
        return canonicalize_existing_file(path);
    }

    let package_spec = split_package_specifier(specifier).ok_or_else(|| {
        JsErrorBox::generic(format!("failed to resolve css import \"{specifier}\""))
    })?;
    let package_dir =
        find_node_modules_package_dir(&package_spec.package_name, importer_dir, root_dir)
            .ok_or_else(|| {
                JsErrorBox::generic(format!("failed to resolve css import \"{specifier}\""))
            })?;

    if let Some(subpath) = package_spec.subpath.as_deref() {
        let candidate = package_dir.join(subpath);
        if let Ok(resolved) = canonicalize_existing_file(&candidate) {
            return Ok(resolved);
        }
    }

    resolve_package_style_export(&package_dir, specifier, package_spec.subpath.as_deref())
}

#[cfg(test)]
mod tests {
    use std::{
        fs,
        path::{Path, PathBuf},
        sync::atomic::{AtomicU64, Ordering},
        time::{SystemTime, UNIX_EPOCH},
    };

    use super::*;

    static NEXT_DIR_ID: AtomicU64 = AtomicU64::new(0);

    struct TestDir {
        path: PathBuf,
    }

    impl TestDir {
        fn new() -> Self {
            let id = NEXT_DIR_ID.fetch_add(1, Ordering::Relaxed);
            let millis = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("system time should be after epoch")
                .as_millis();
            let path = std::env::temp_dir().join(format!(
                "gdansk-vite-runtime-{millis}-{id}-{}",
                std::process::id()
            ));
            fs::create_dir_all(&path).expect("test dir should be created");
            Self { path }
        }

        fn path(&self) -> &Path {
            &self.path
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.path);
        }
    }

    fn canonical(path: &Path) -> PathBuf {
        dunce::simplified(
            &path
                .canonicalize()
                .expect("expected path to be canonicalizable"),
        )
        .to_path_buf()
    }

    #[test]
    fn resolves_bare_package_with_oxc_resolver() {
        let temp_dir = TestDir::new();
        let pages = temp_dir.path().join("views");
        let package_dir = pages.join("node_modules").join("sample-plugin");
        fs::create_dir_all(&package_dir).expect("package dir should exist");
        fs::write(
            package_dir.join("package.json"),
            r#"{
  "name": "sample-plugin",
  "type": "module",
  "exports": {
    ".": "./index.js"
  }
}
"#,
        )
        .expect("package json should be written");
        fs::write(package_dir.join("index.js"), "export default {};\n")
            .expect("index should be written");

        let shared = ViteRuntimeShared::new(&pages);
        let resolved = shared
            .resolve_js_module_specifier("sample-plugin", Some(BOOTSTRAP_SPECIFIER), true)
            .expect("specifier should resolve");
        let expected = canonical(&package_dir.join("index.js"));

        assert_eq!(
            canonical(
                resolved
                    .to_file_path()
                    .expect("resolved specifier should be a file path")
                    .as_path(),
            ),
            expected
        );
    }

    #[test]
    fn resolves_css_style_export() {
        let temp_dir = TestDir::new();
        let pages = temp_dir.path().join("views");
        let package_dir = pages.join("node_modules").join("@scope").join("styles");
        fs::create_dir_all(package_dir.join("dist")).expect("package dir should exist");
        fs::write(
            package_dir.join("package.json"),
            r#"{
  "name": "@scope/styles",
  "exports": {
    ".": {
      "style": "./dist/main.css"
    }
  }
}
"#,
        )
        .expect("package json should be written");
        fs::write(package_dir.join("dist/main.css"), "body { color: red; }\n")
            .expect("css file should be written");

        let resolved = resolve_css_import_path("@scope/styles", &pages, &pages)
            .expect("css import should resolve");
        let expected = canonical(&package_dir.join("dist/main.css"));
        assert_eq!(resolved, expected);
    }

    #[test]
    fn rejects_unsupported_node_builtin() {
        let temp_dir = TestDir::new();
        let pages = temp_dir.path().join("views");
        fs::create_dir_all(&pages).expect("pages dir should exist");
        let shared = ViteRuntimeShared::new(&pages);

        let err = shared
            .resolve_js_module_specifier("node:os", Some(BOOTSTRAP_SPECIFIER), true)
            .expect_err("unsupported builtin should fail");
        assert!(
            err.to_string()
                .contains("unsupported node builtin module: node:os")
        );
    }

    #[test]
    fn embedded_runtime_supports_fs_promises_stat() {
        let temp_dir = TestDir::new();
        let pages = temp_dir.path().join("views");
        let plugin_dir = pages.join("plugins");
        fs::create_dir_all(&plugin_dir).expect("plugin dir should exist");
        fs::write(pages.join("comment.txt"), "from-runtime\n").expect("comment should be written");
        fs::write(
            plugin_dir.join("read-comment.mjs"),
            r#"
import fs from "fs/promises";

export default function (options) {
  return {
    name: "read-comment",
    transform: {
      filter: {
        id: {
          include: [/\.css$/],
        },
      },
      async handler(source, id) {
        if (!id.endsWith(".css")) {
          return source;
        }
        const stat = await fs.stat(options.watchFile);
        if (!stat.isFile()) {
          throw new Error("expected file");
        }
        const comment = (await fs.readFile(options.watchFile, "utf8")).trim();
        return `${source}\n/* ${comment} */\n`;
      },
    },
  };
}
"#,
        )
        .expect("plugin should be written");

        let plugin_path = Url::from_file_path(plugin_dir.join("read-comment.mjs"))
            .expect("plugin path should convert to url")
            .to_string();
        let result = run_embedded_vite_plugins(
            &[VitePluginSpec {
                specifier: plugin_path,
                options: serde_json::json!({ "watchFile": "comment.txt" }),
            }],
            &pages,
            vec![PluginAssetInput {
                filename: "style.css".to_owned(),
                path: pages.join("style.css").to_string_lossy().into_owned(),
                code: "body{}".to_owned(),
            }],
        )
        .expect("embedded runtime should succeed");

        assert_eq!(result.assets.len(), 1);
        assert!(result.assets[0].code.contains("from-runtime"));
    }

    #[test]
    fn embedded_runtime_supports_node_path() {
        let temp_dir = TestDir::new();
        let pages = temp_dir.path().join("views");
        let plugin_dir = pages.join("plugins");
        fs::create_dir_all(&plugin_dir).expect("plugin dir should exist");
        fs::write(
            plugin_dir.join("use-node-path.mjs"),
            r#"
import path from "node:path";

export default {
  name: "use-node-path",
  transform: {
    filter: {
      id: {
        include: [/\.css$/],
      },
    },
    handler(source, id) {
      return `${source}\n/* ${path.basename(id)} */\n`;
    },
  },
};
"#,
        )
        .expect("plugin should be written");

        let plugin_path = Url::from_file_path(plugin_dir.join("use-node-path.mjs"))
            .expect("plugin path should convert to url")
            .to_string();
        let result = run_embedded_vite_plugins(
            &[VitePluginSpec {
                specifier: plugin_path,
                options: serde_json::json!({}),
            }],
            &pages,
            vec![PluginAssetInput {
                filename: "style.css".to_owned(),
                path: pages.join("style.css").to_string_lossy().into_owned(),
                code: "body{}".to_owned(),
            }],
        )
        .expect("embedded runtime should succeed");

        assert_eq!(result.assets.len(), 1);
        assert!(result.assets[0].code.contains("style.css"));
    }

    #[test]
    fn embedded_runtime_supports_bare_path() {
        let temp_dir = TestDir::new();
        let pages = temp_dir.path().join("views");
        let plugin_dir = pages.join("plugins");
        fs::create_dir_all(&plugin_dir).expect("plugin dir should exist");
        fs::write(
            plugin_dir.join("use-bare-path.mjs"),
            r#"
import path from "path";

export default {
  name: "use-bare-path",
  transform: {
    filter: {
      id: {
        include: [/\.css$/],
      },
    },
    handler(source, id) {
      return `${source}\n/* ${path.basename(id)} */\n`;
    },
  },
};
"#,
        )
        .expect("plugin should be written");

        let plugin_path = Url::from_file_path(plugin_dir.join("use-bare-path.mjs"))
            .expect("plugin path should convert to url")
            .to_string();
        let result = run_embedded_vite_plugins(
            &[VitePluginSpec {
                specifier: plugin_path,
                options: serde_json::json!({}),
            }],
            &pages,
            vec![PluginAssetInput {
                filename: "style.css".to_owned(),
                path: pages.join("style.css").to_string_lossy().into_owned(),
                code: "body{}".to_owned(),
            }],
        )
        .expect("embedded runtime should succeed");

        assert_eq!(result.assets.len(), 1);
        assert!(result.assets[0].code.contains("style.css"));
    }
}
