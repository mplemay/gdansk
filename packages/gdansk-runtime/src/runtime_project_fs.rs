use std::{
    fs,
    path::{Component, Path, PathBuf},
    sync::Arc,
};

use deno_core::{
    ModuleSpecifier, OpState, op2,
    serde_json::{self, Value},
};
use deno_error::JsErrorBox;
use oxc_resolver::{ResolveOptions, Resolver};
use serde::Serialize;
use url::Url;

#[derive(Debug)]
pub(crate) struct ScriptProjectFsState {
    pub(crate) shared: Arc<ScriptProjectFsShared>,
}

#[derive(Debug)]
pub(crate) struct ScriptProjectFsShared {
    pages: PathBuf,
    js_resolver: Resolver,
}

impl ScriptProjectFsShared {
    pub(crate) fn new(pages: PathBuf) -> Self {
        let js_resolver = Resolver::new(
            ResolveOptions::default().with_condition_names(&["node", "import", "default"]),
        );
        Self {
            pages,
            js_resolver,
        }
    }

    fn resolve_input_path(&self, input: &str) -> Result<PathBuf, JsErrorBox> {
        if input.starts_with("file://") {
            let specifier =
                ModuleSpecifier::parse(input).map_err(|err| JsErrorBox::generic(err.to_string()))?;
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

        let resolution = match importer {
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

fn unsupported_node_builtin(specifier: &str) -> JsErrorBox {
    JsErrorBox::generic(format!("unsupported node builtin module: {specifier}"))
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

#[op2]
#[string]
fn op_gdansk_runtime_read_text_file(
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

    let shared = state.borrow::<ScriptProjectFsState>().shared.clone();
    let path = shared.resolve_input_path(&path)?;
    fs::read_to_string(path).map_err(|err| JsErrorBox::generic(err.to_string()))
}

#[op2]
#[string]
fn op_gdansk_runtime_realpath_sync(
    state: &mut OpState,
    #[string] path: String,
) -> Result<String, JsErrorBox> {
    let shared = state.borrow::<ScriptProjectFsState>().shared.clone();
    let path = shared.resolve_input_path(&path)?;
    canonicalize_existing_file(&path).map(|path| path.to_string_lossy().into_owned())
}

#[op2]
#[string]
fn op_gdansk_runtime_stat(state: &mut OpState, #[string] path: String) -> Result<String, JsErrorBox> {
    let shared = state.borrow::<ScriptProjectFsState>().shared.clone();
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
fn op_gdansk_runtime_read_dir(
    state: &mut OpState,
    #[string] path: String,
) -> Result<String, JsErrorBox> {
    let shared = state.borrow::<ScriptProjectFsState>().shared.clone();
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
fn op_gdansk_runtime_resolve(
    state: &mut OpState,
    #[string] specifier: String,
    #[string] importer: Option<String>,
    #[string] resolver_kind: String,
) -> Result<String, JsErrorBox> {
    let shared = state.borrow::<ScriptProjectFsState>().shared.clone();
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
fn op_gdansk_runtime_normalize_watch_file(
    state: &mut OpState,
    #[string] file: String,
) -> Result<String, JsErrorBox> {
    let shared = state.borrow::<ScriptProjectFsState>().shared.clone();
    shared.normalize_watch_file(&file)
}

#[op2]
#[string]
fn op_gdansk_runtime_path_basename(#[string] path: String) -> String {
    basename_string(&path)
}

#[op2]
#[string]
fn op_gdansk_runtime_path_dirname(#[string] path: String) -> String {
    dirname_string(&path)
}

#[op2]
#[string]
fn op_gdansk_runtime_path_extname(#[string] path: String) -> String {
    extname_string(&path)
}

#[op2]
#[string]
fn op_gdansk_runtime_path_relative(
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
fn op_gdansk_runtime_path_resolve(#[string] paths: String) -> Result<String, JsErrorBox> {
    resolve_string_path_segments(&paths)
}

#[op2]
#[string]
fn op_gdansk_runtime_path_posix_join(#[string] paths: String) -> Result<String, JsErrorBox> {
    join_posix_segments(&paths)
}

#[op2]
#[string]
fn op_gdansk_runtime_file_url_to_path(#[string] url: String) -> Result<String, JsErrorBox> {
    Url::parse(&url)
        .map_err(|err| JsErrorBox::generic(err.to_string()))?
        .to_file_path()
        .map_err(|_| JsErrorBox::generic(format!("unsupported file URL: {url}")))
        .map(|path| path.to_string_lossy().into_owned())
}

#[op2]
#[string]
fn op_gdansk_runtime_path_to_file_url(#[string] path: String) -> Result<String, JsErrorBox> {
    let path = absolute_lexical_path(Path::new(&path))?;
    Url::from_file_path(&path)
        .map_err(|_| JsErrorBox::generic(format!("failed to resolve path {}", path.display())))
        .map(|url| url.to_string())
}

deno_core::extension!(
    gdansk_runtime_project_fs_ext,
    ops = [
        op_gdansk_runtime_read_text_file,
        op_gdansk_runtime_read_dir,
        op_gdansk_runtime_realpath_sync,
        op_gdansk_runtime_stat,
        op_gdansk_runtime_resolve,
        op_gdansk_runtime_normalize_watch_file,
        op_gdansk_runtime_path_basename,
        op_gdansk_runtime_path_dirname,
        op_gdansk_runtime_path_extname,
        op_gdansk_runtime_path_relative,
        op_gdansk_runtime_path_resolve,
        op_gdansk_runtime_path_posix_join,
        op_gdansk_runtime_file_url_to_path,
        op_gdansk_runtime_path_to_file_url,
    ],
    options = {
        shared: Arc<ScriptProjectFsShared>,
    },
    state = |state, options| {
        state.put(ScriptProjectFsState {
            shared: options.shared,
        });
    }
);
