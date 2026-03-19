use std::{
    collections::{HashMap, HashSet},
    fmt, fs,
    path::{Path, PathBuf},
};

use deno_core::serde_json::Value;
use lightningcss::{
    bundler::{
        BundleErrorKind as CssBundleErrorKind, Bundler as CssBundler,
        FileProvider as CssFileProvider, ResolveResult, SourceProvider,
    },
    printer::PrinterOptions,
    stylesheet::{MinifyOptions, ParserOptions},
};

#[cfg(not(test))]
use std::{
    borrow::Cow,
    sync::{Arc, Mutex},
};

#[cfg(not(test))]
use rolldown::plugin::{
    __inner::SharedPluginable, HookBuildStartArgs, HookLoadArgs, HookLoadOutput, HookLoadReturn,
    HookResolveIdArgs, HookResolveIdOutput, HookResolveIdReturn, HookUsage, Plugin, PluginContext,
    PluginContextResolveOptions, SharedLoadPluginContext,
};
#[cfg(not(test))]
use rolldown_common::{Output, OutputAsset, StrOrBytes};

use crate::bundle::{BundleError, NormalizedPage, path_to_utf8};

#[cfg(not(test))]
use super::shared::LIGHTNINGCSS_PLUGIN_ID;
use super::shared::{GDANSK_CSS_STUB_PREFIX, client_entry_import};

#[derive(Debug)]
enum CssProviderError {
    Io(std::io::Error),
    Bundle(BundleError),
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

#[derive(Debug, Clone, Default, PartialEq, Eq)]
struct CssGraphModule {
    imported_ids: Vec<String>,
    css_imports: Vec<String>,
}

struct CssSourceProvider {
    cwd: PathBuf,
    inner: CssFileProvider,
    virtual_sources: HashMap<PathBuf, String>,
    virtual_resolutions: HashMap<PathBuf, HashMap<String, PathBuf>>,
}

impl CssSourceProvider {
    fn new(cwd: &Path) -> Self {
        Self {
            cwd: cwd.to_path_buf(),
            inner: CssFileProvider::new(),
            virtual_sources: HashMap::new(),
            virtual_resolutions: HashMap::new(),
        }
    }

    fn with_virtual_entry(
        cwd: &Path,
        entry_path: PathBuf,
        entry_source: String,
        resolutions: HashMap<String, PathBuf>,
    ) -> Self {
        let mut provider = Self::new(cwd);
        provider
            .virtual_sources
            .insert(entry_path.clone(), entry_source);
        provider.virtual_resolutions.insert(entry_path, resolutions);
        provider
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
    entry: &'a Value,
    specifier: &str,
    export_key: &str,
) -> Result<&'a str, BundleError> {
    match entry {
        Value::String(path) => Ok(path),
        Value::Object(_) => entry.get("style").and_then(Value::as_str).ok_or_else(|| {
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
    let parsed: Value = deno_core::serde_json::from_str(&package_json).map_err(|err| {
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

fn render_css_bundle(
    css_paths: &[String],
    cwd: &Path,
    minify: bool,
) -> Result<String, BundleError> {
    let resolved_paths = css_paths
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
        .collect::<Result<Vec<_>, _>>()?;
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
) -> Vec<String> {
    fn visit(
        module_id: &str,
        modules: &HashMap<String, CssGraphModule>,
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

        for css_import in &module.css_imports {
            if visited_css.insert(css_import.clone()) {
                ordered_css.push(css_import.clone());
            }
        }

        for imported_id in &module.imported_ids {
            if imported_id.starts_with(GDANSK_CSS_STUB_PREFIX) {
                continue;
            }
            visit(
                imported_id,
                modules,
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
        &mut visited_modules,
        &mut visited_css,
        &mut ordered_css,
    );
    ordered_css
}

fn find_client_entry_module_id(
    page: &NormalizedPage,
    entry_module_ids: &[String],
) -> Option<String> {
    let entry_import = client_entry_import(&page.import, page.app);
    for module_id in entry_module_ids {
        let normalized_module_id = module_id.replace('\\', "/");
        if normalized_module_id == entry_import
            || normalized_module_id.ends_with(&entry_import)
            || normalized_module_id.ends_with(&page.import)
        {
            return Some(module_id.clone());
        }
    }

    None
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct RenderedCssOutput {
    filename: String,
    code: Option<String>,
}

fn build_css_outputs(
    normalized: &[NormalizedPage],
    entry_module_ids: &HashMap<String, String>,
    modules: &HashMap<String, CssGraphModule>,
    cwd: &Path,
    minify: bool,
) -> Result<Vec<RenderedCssOutput>, BundleError> {
    let mut outputs = Vec::with_capacity(normalized.len());
    for page in normalized {
        let entry_id = entry_module_ids.get(&page.import).ok_or_else(|| {
            BundleError::runtime(format!(
                "failed to resolve client entry for css output: {}",
                page.import
            ))
        })?;
        let css_imports = collect_entry_css_imports(entry_id, modules);
        let filename =
            path_to_utf8(&page.client_css_path, "client css output path")?.replace('\\', "/");

        if css_imports.is_empty() {
            outputs.push(RenderedCssOutput {
                filename,
                code: None,
            });
            continue;
        }

        let mut bundled = render_css_bundle(&css_imports, cwd, minify)?;
        if !bundled.ends_with('\n') {
            bundled.push('\n');
        }

        outputs.push(RenderedCssOutput {
            filename,
            code: Some(bundled),
        });
    }

    Ok(outputs)
}

#[cfg(not(test))]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum LightningCssPluginMode {
    Client,
    Server,
}

#[cfg(not(test))]
#[derive(Debug)]
struct LightningCssClientState {
    normalized: Vec<NormalizedPage>,
    cwd: PathBuf,
    output_dir: PathBuf,
    minify: bool,
    css_imports: Mutex<HashMap<String, Vec<String>>>,
}

#[cfg(not(test))]
#[derive(Debug)]
struct LightningCssPlugin {
    mode: LightningCssPluginMode,
    client_state: Option<LightningCssClientState>,
}

#[cfg(not(test))]
impl LightningCssPlugin {
    fn client(normalized: &[NormalizedPage], cwd: &Path, output_dir: &Path, minify: bool) -> Self {
        Self {
            mode: LightningCssPluginMode::Client,
            client_state: Some(LightningCssClientState {
                normalized: normalized.to_vec(),
                cwd: cwd.to_path_buf(),
                output_dir: output_dir.to_path_buf(),
                minify,
                css_imports: Mutex::new(HashMap::new()),
            }),
        }
    }

    fn server() -> Self {
        Self {
            mode: LightningCssPluginMode::Server,
            client_state: None,
        }
    }

    fn resolve_virtual_id(specifier: &str, importer: Option<&str>) -> String {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        std::hash::Hash::hash(&importer, &mut hasher);
        std::hash::Hash::hash(&specifier, &mut hasher);
        format!(
            "{GDANSK_CSS_STUB_PREFIX}{:016x}",
            std::hash::Hasher::finish(&hasher)
        )
    }

    fn is_bare_specifier(specifier: &str) -> bool {
        !specifier.starts_with("./")
            && !specifier.starts_with("../")
            && !Path::new(specifier).is_absolute()
    }

    async fn resolve_css_import(
        &self,
        ctx: &PluginContext,
        args: &HookResolveIdArgs<'_>,
    ) -> HookResolveIdReturn {
        if args.kind != PluginContextResolveOptions::default().import_kind {
            return Ok(None);
        }

        let should_probe =
            args.specifier.ends_with(".css") || Self::is_bare_specifier(args.specifier);
        if !should_probe {
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
                if args.specifier.ends_with(".css") {
                    return Err(std::io::Error::other(format!(
                        "failed to resolve css import \"{}\": {err}",
                        args.specifier
                    ))
                    .into());
                }
                return Ok(None);
            }
        };
        let resolved = match resolution {
            Ok(resolved) => resolved,
            Err(err) => {
                if args.specifier.ends_with(".css") {
                    return Err(std::io::Error::other(format!(
                        "failed to resolve css import \"{}\": {err}",
                        args.specifier
                    ))
                    .into());
                }
                return Ok(None);
            }
        };

        if !resolved.id.as_str().ends_with(".css") {
            return Ok(None);
        }

        if let Some(client_state) = &self.client_state
            && let Some(importer) = args.importer
        {
            client_state
                .css_imports
                .lock()
                .expect("css graph poisoned")
                .entry(importer.to_owned())
                .or_default()
                .push(resolved.id.to_string());
        }

        Ok(Some(HookResolveIdOutput::from_id(
            Self::resolve_virtual_id(args.specifier, args.importer),
        )))
    }
}

#[cfg(not(test))]
pub(super) fn client_plugin(
    normalized: &[NormalizedPage],
    cwd: &Path,
    output_dir: &Path,
    minify: bool,
) -> SharedPluginable {
    Arc::new(LightningCssPlugin::client(
        normalized, cwd, output_dir, minify,
    ))
}

#[cfg(not(test))]
pub(super) fn server_plugin() -> SharedPluginable {
    Arc::new(LightningCssPlugin::server())
}

#[cfg(not(test))]
impl Plugin for LightningCssPlugin {
    fn name(&self) -> Cow<'static, str> {
        Cow::Borrowed(LIGHTNINGCSS_PLUGIN_ID)
    }

    async fn build_start(
        &self,
        _ctx: &PluginContext,
        _args: &HookBuildStartArgs<'_>,
    ) -> rolldown::plugin::HookNoopReturn {
        let Some(client_state) = &self.client_state else {
            return Ok(());
        };

        client_state
            .css_imports
            .lock()
            .expect("css graph poisoned")
            .clear();
        Ok(())
    }

    async fn resolve_id(
        &self,
        ctx: &PluginContext,
        args: &HookResolveIdArgs<'_>,
    ) -> HookResolveIdReturn {
        self.resolve_css_import(ctx, args).await
    }

    async fn load(&self, _ctx: SharedLoadPluginContext, args: &HookLoadArgs<'_>) -> HookLoadReturn {
        if !args.id.starts_with(GDANSK_CSS_STUB_PREFIX) {
            return Ok(None);
        }

        Ok(Some(HookLoadOutput {
            code: "const gdanskCssStub = {};\nexport default gdanskCssStub;\n".into(),
            ..Default::default()
        }))
    }

    async fn generate_bundle(
        &self,
        ctx: &PluginContext,
        args: &mut rolldown::plugin::HookGenerateBundleArgs<'_>,
    ) -> rolldown::plugin::HookNoopReturn {
        if self.mode != LightningCssPluginMode::Client {
            return Ok(());
        }

        let Some(client_state) = &self.client_state else {
            return Ok(());
        };

        let mut modules = HashMap::new();
        let mut discovered_entry_modules = Vec::new();
        for module_id in ctx.get_module_ids() {
            if let Some(module_info) = ctx.get_module_info(module_id.as_ref()) {
                if module_info.is_entry {
                    discovered_entry_modules.push(module_id.to_string());
                }
                modules.insert(
                    module_id.to_string(),
                    CssGraphModule {
                        imported_ids: module_info
                            .imported_ids
                            .iter()
                            .map(ToString::to_string)
                            .collect(),
                        css_imports: Vec::new(),
                    },
                );
            }
        }

        for (importer, css_imports) in client_state
            .css_imports
            .lock()
            .expect("css graph poisoned")
            .iter()
        {
            modules.entry(importer.clone()).or_default().css_imports = css_imports.clone();
        }

        let mut entry_module_ids = HashMap::with_capacity(client_state.normalized.len());
        for page in &client_state.normalized {
            let entry_module_id = find_client_entry_module_id(page, &discovered_entry_modules)
                .ok_or_else(|| {
                    std::io::Error::other(format!(
                        "failed to find client entry in module graph: {}",
                        page.import
                    ))
                })?;
            entry_module_ids.insert(page.import.clone(), entry_module_id);
        }

        let css_outputs = build_css_outputs(
            &client_state.normalized,
            &entry_module_ids,
            &modules,
            &client_state.cwd,
            client_state.minify,
        )
        .map_err(|err| std::io::Error::other(err.to_string()))?;

        let output_root = if client_state.output_dir.is_absolute() {
            client_state.output_dir.clone()
        } else {
            client_state.cwd.join(&client_state.output_dir)
        };
        let mut pending_assets = HashMap::new();
        let mut deleted_assets = HashSet::new();

        for asset in css_outputs {
            match asset.code {
                Some(code) => {
                    pending_assets.insert(asset.filename, code);
                }
                None => {
                    deleted_assets.insert(asset.filename.clone());
                    let stale_path = output_root.join(&asset.filename);
                    if stale_path.exists() {
                        fs::remove_file(&stale_path).map_err(|err| {
                            std::io::Error::other(format!(
                                "failed to remove stale css output {}: {err}",
                                stale_path.display()
                            ))
                        })?;
                    }
                }
            }
        }

        let mut existing_assets = HashSet::new();
        args.bundle.retain_mut(|output| match output {
            Output::Asset(asset) => {
                if deleted_assets.contains(asset.filename.as_str()) {
                    return false;
                }
                if let Some(code) = pending_assets.remove(asset.filename.as_str()) {
                    existing_assets.insert(asset.filename.to_string());
                    *output = Output::Asset(Arc::new(OutputAsset {
                        names: asset.names.clone(),
                        original_file_names: asset.original_file_names.clone(),
                        filename: asset.filename.clone(),
                        source: StrOrBytes::from(code),
                    }));
                    return true;
                }
                true
            }
            Output::Chunk(_) => true,
        });

        for (filename, code) in pending_assets {
            if existing_assets.contains(&filename) {
                continue;
            }
            args.bundle.push(Output::Asset(Arc::new(OutputAsset {
                names: Vec::new(),
                original_file_names: Vec::new(),
                filename: filename.into(),
                source: StrOrBytes::from(code),
            })));
        }

        Ok(())
    }

    fn register_hook_usage(&self) -> HookUsage {
        HookUsage::BuildStart | HookUsage::ResolveId | HookUsage::Load | HookUsage::GenerateBundle
    }
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
            let root = std::env::temp_dir().join(format!(
                "gdansk-lightningcss-test-{}-{}",
                std::process::id(),
                id
            ));
            fs::create_dir_all(&root).expect("failed to create temp project root");
            Self { root }
        }

        fn create_file(&self, relative: &str) {
            self.write_file(relative, "export default null;\n");
        }

        fn write_file(&self, relative: &str, contents: &str) {
            let file_path = self.root.join(relative);
            if let Some(parent) = file_path.parent() {
                fs::create_dir_all(parent).expect("failed to create parent directories");
            }
            fs::write(file_path, contents).expect("failed to write file");
        }
    }

    impl Drop for TempProject {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
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

    fn css_graph_module(imported_ids: &[&str], css_imports: Vec<String>) -> CssGraphModule {
        CssGraphModule {
            imported_ids: imported_ids
                .iter()
                .map(|value| (*value).to_string())
                .collect(),
            css_imports,
        }
    }

    fn normalized_page(
        import: &str,
        app: bool,
        client_name: &str,
        client_css_path: &str,
    ) -> NormalizedPage {
        NormalizedPage {
            import: import.to_string(),
            app,
            ssr: false,
            client_name: client_name.to_string(),
            client_css_path: PathBuf::from(client_css_path),
            server_name: None,
        }
    }

    #[test]
    fn client_entry_lookup_matches_windows_nested_non_app_paths() {
        let page = normalized_page("home/page.tsx", false, "home/page", "home/page.css");
        let module_id = r"D:\work\proj\home\page.tsx".to_string();

        assert_eq!(
            find_client_entry_module_id(&page, std::slice::from_ref(&module_id)),
            Some(module_id)
        );
    }

    #[test]
    fn client_entry_lookup_matches_windows_app_entry_paths() {
        let page = normalized_page(
            "apps/simple/page.tsx",
            true,
            "simple/client",
            "simple/client.css",
        );
        let module_id = r"D:\work\proj\apps\simple\page.tsx?gdansk-app-entry".to_string();

        assert_eq!(
            find_client_entry_module_id(&page, std::slice::from_ref(&module_id)),
            Some(module_id)
        );
    }

    #[test]
    fn css_graph_collects_nested_component_styles() {
        let modules = HashMap::from([
            (
                "page".to_string(),
                css_graph_module(&["button", "layout"], vec!["page.css".to_string()]),
            ),
            (
                "button".to_string(),
                css_graph_module(&["shared"], vec!["button.css".to_string()]),
            ),
            (
                "layout".to_string(),
                css_graph_module(&[], vec!["layout.css".to_string()]),
            ),
            (
                "shared".to_string(),
                css_graph_module(&[], vec!["shared.css".to_string()]),
            ),
        ]);

        let imports = collect_entry_css_imports("page", &modules);

        assert_eq!(
            imports,
            vec![
                "page.css".to_string(),
                "button.css".to_string(),
                "shared.css".to_string(),
                "layout.css".to_string(),
            ]
        );
    }

    #[test]
    fn css_graph_deduplicates_shared_child_styles() {
        let modules = HashMap::from([
            (
                "page".to_string(),
                css_graph_module(&["left", "right"], Vec::new()),
            ),
            (
                "left".to_string(),
                css_graph_module(&["shared"], vec!["left.css".to_string()]),
            ),
            (
                "right".to_string(),
                css_graph_module(&["shared"], vec!["right.css".to_string()]),
            ),
            (
                "shared".to_string(),
                css_graph_module(&[], vec!["shared.css".to_string()]),
            ),
        ]);

        let imports = collect_entry_css_imports("page", &modules);

        assert_eq!(
            imports,
            vec![
                "left.css".to_string(),
                "shared.css".to_string(),
                "right.css".to_string(),
            ]
        );
    }

    #[test]
    fn css_graph_preserves_import_order_within_a_module() {
        let modules = HashMap::from([(
            "page".to_string(),
            css_graph_module(&[], vec!["first.css".to_string(), "second.css".to_string()]),
        )]);

        let imports = collect_entry_css_imports("page", &modules);

        assert_eq!(
            imports,
            vec!["first.css".to_string(), "second.css".to_string()]
        );
    }

    #[test]
    fn css_graph_skips_virtual_css_stub_modules() {
        let modules = HashMap::from([(
            "page".to_string(),
            css_graph_module(
                &[&format!("{GDANSK_CSS_STUB_PREFIX}deadbeef")],
                vec!["page.css".to_string()],
            ),
        )]);

        let imports = collect_entry_css_imports("page", &modules);

        assert_eq!(imports, vec!["page.css".to_string()]);
    }

    #[test]
    fn resolve_css_import_path_resolves_package_root_style_export() {
        let project = TempProject::new();
        project.create_file("src/page.tsx");
        project.write_file(
            "node_modules/pkg/package.json",
            r#"{"exports":{".":{"style":"./dist/root.css"}}}"#,
        );
        project.write_file("node_modules/pkg/dist/root.css", ".root { color: red; }\n");

        let resolved =
            resolve_css_import_path("pkg", &project.root.join("src"), &project.root).unwrap();

        assert_eq!(
            resolved,
            canonical(&project.root.join("node_modules/pkg/dist/root.css"))
        );
    }

    #[test]
    fn resolve_css_import_path_resolves_exported_subpath_without_physical_directory() {
        let project = TempProject::new();
        project.create_file("src/page.tsx");
        project.write_file(
            "node_modules/pkg/package.json",
            r#"{"exports":{"./theme":"./dist/theme.css"}}"#,
        );
        project.write_file(
            "node_modules/pkg/dist/theme.css",
            ".theme { color: blue; }\n",
        );

        let resolved =
            resolve_css_import_path("pkg/theme", &project.root.join("src"), &project.root).unwrap();

        assert_eq!(
            resolved,
            canonical(&project.root.join("node_modules/pkg/dist/theme.css"))
        );
    }

    #[test]
    fn resolve_css_import_path_prefers_physical_package_subpaths() {
        let project = TempProject::new();
        project.create_file("src/page.tsx");
        project.write_file(
            "node_modules/pkg/package.json",
            r#"{"exports":{"./theme":"./dist/theme.css"}}"#,
        );
        project.write_file(
            "node_modules/pkg/theme.css",
            ".physical { color: black; }\n",
        );
        project.write_file(
            "node_modules/pkg/dist/theme.css",
            ".exported { color: green; }\n",
        );

        let resolved =
            resolve_css_import_path("pkg/theme.css", &project.root.join("src"), &project.root)
                .unwrap();

        assert_eq!(
            resolved,
            canonical(&project.root.join("node_modules/pkg/theme.css"))
        );
    }

    #[test]
    fn resolve_css_import_path_handles_scoped_package_subpaths() {
        let project = TempProject::new();
        project.create_file("src/page.tsx");
        project.write_file(
            "node_modules/@scope/pkg/package.json",
            r#"{"exports":{"./theme":"./dist/theme.css"}}"#,
        );
        project.write_file(
            "node_modules/@scope/pkg/dist/theme.css",
            ".scoped { color: purple; }\n",
        );

        let resolved =
            resolve_css_import_path("@scope/pkg/theme", &project.root.join("src"), &project.root)
                .unwrap();

        assert_eq!(
            resolved,
            canonical(&project.root.join("node_modules/@scope/pkg/dist/theme.css"))
        );
    }

    #[test]
    fn build_css_outputs_includes_child_component_styles() {
        let project = TempProject::new();
        project.create_file("page.tsx");
        project.write_file("Button.css", ".button { color: red; }\n");

        let normalized = vec![normalized_page("page.tsx", false, "page", "page.css")];
        let entry_module_ids = HashMap::from([("page.tsx".to_string(), "page.tsx".to_string())]);
        let modules = HashMap::from([
            (
                "page.tsx".to_string(),
                css_graph_module(&["Button.tsx"], Vec::new()),
            ),
            (
                "Button.tsx".to_string(),
                css_graph_module(
                    &[],
                    vec![
                        project
                            .root
                            .join("Button.css")
                            .to_string_lossy()
                            .into_owned(),
                    ],
                ),
            ),
        ]);

        let outputs = build_css_outputs(
            &normalized,
            &entry_module_ids,
            &modules,
            &project.root,
            false,
        )
        .expect("expected css output to build");

        assert_eq!(outputs.len(), 1);
        assert_eq!(outputs[0].filename, "page.css");
        assert!(
            outputs[0]
                .code
                .as_ref()
                .is_some_and(|css| css.contains(".button"))
        );
    }

    #[test]
    fn build_css_outputs_includes_package_styles_reached_from_js() {
        let project = TempProject::new();
        project.create_file("page.tsx");
        project.write_file(
            "node_modules/my-lib/dist/theme.css",
            ".theme { color: orange; }\n",
        );

        let normalized = vec![normalized_page("page.tsx", false, "page", "page.css")];
        let entry_module_ids = HashMap::from([("page.tsx".to_string(), "page.tsx".to_string())]);
        let modules = HashMap::from([(
            "page.tsx".to_string(),
            css_graph_module(
                &[],
                vec![
                    project
                        .root
                        .join("node_modules/my-lib/dist/theme.css")
                        .to_string_lossy()
                        .into_owned(),
                ],
            ),
        )]);

        let outputs = build_css_outputs(
            &normalized,
            &entry_module_ids,
            &modules,
            &project.root,
            false,
        )
        .expect("expected css output to build");

        assert_eq!(outputs.len(), 1);
        assert_eq!(outputs[0].filename, "page.css");
        assert!(
            outputs[0]
                .code
                .as_ref()
                .is_some_and(|css| css.contains(".theme"))
        );
    }
}
