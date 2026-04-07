use std::{
    collections::BTreeSet,
    fs,
    path::{Path, PathBuf},
    sync::LazyLock,
    time::UNIX_EPOCH,
};

use regex::Regex;
use serde_json::Value;
use url::Url;
use walkdir::{DirEntry, WalkDir};

#[cfg(not(test))]
use pyo3::{
    exceptions::{PyFileNotFoundError, PyRuntimeError},
    prelude::*,
};

const MAX_TOKEN_LEN: usize = 128;
const CONTENT_EXTENSIONS: &[&str] = &["css", "html", "js", "jsx", "md", "mdx", "ts", "tsx"];
const IGNORED_DIRECTORIES: &[&str] = &[".gdansk", ".git", "build", "dist", "node_modules"];

static CANDIDATE_PATTERN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[A-Za-z0-9_:\-./\[\]%]+").expect("candidate regex must compile"));
static CSS_IMPORT_PATTERN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"@import\s+(?:url\s*\(\s*['"]?([^'"\)]+)['"]?\s*\)|['"]([^'"]+)['"])\s*;"#)
        .expect("css import regex must compile")
});

#[derive(Clone, Debug, Eq, PartialEq)]
struct CandidateFileStamp {
    modified_ms: Option<u128>,
    path: PathBuf,
}

#[derive(Clone, Debug)]
struct CandidateCache {
    candidates: Vec<String>,
    files: Vec<CandidateFileStamp>,
}

#[derive(Clone, Debug)]
struct PreparedTransformData {
    candidates: Vec<String>,
    css: String,
    tailwind_module_url: String,
}

#[derive(Debug)]
enum TailwindCssError {
    FileNotFound(String),
    Runtime(String),
}

impl TailwindCssError {
    fn message(&self) -> &str {
        match self {
            Self::FileNotFound(message) | Self::Runtime(message) => message,
        }
    }
}

impl std::fmt::Display for TailwindCssError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.message())
    }
}

#[cfg(not(test))]
impl TailwindCssError {
    fn into_pyerr(self) -> PyErr {
        match self {
            Self::FileNotFound(message) => PyFileNotFoundError::new_err(message),
            Self::Runtime(message) => PyRuntimeError::new_err(message),
        }
    }
}

#[cfg_attr(not(test), pyclass(module = "gdansk_tailwindcss._core", frozen))]
struct PreparedTransform {
    candidates: Vec<String>,
    css: String,
    tailwind_module_url: String,
}

impl From<PreparedTransformData> for PreparedTransform {
    fn from(value: PreparedTransformData) -> Self {
        Self {
            candidates: value.candidates,
            css: value.css,
            tailwind_module_url: value.tailwind_module_url,
        }
    }
}

#[cfg(not(test))]
#[pymethods]
impl PreparedTransform {
    #[getter]
    fn candidates(&self) -> Vec<String> {
        self.candidates.clone()
    }

    #[getter]
    fn css(&self) -> String {
        self.css.clone()
    }

    #[getter]
    fn tailwind_module_url(&self) -> String {
        self.tailwind_module_url.clone()
    }
}

#[cfg_attr(not(test), pyclass(module = "gdansk_tailwindcss._core"))]
struct TailwindCssTransformer {
    candidate_cache: Option<CandidateCache>,
    root: PathBuf,
    tailwind_module_url: Option<String>,
}

impl TailwindCssTransformer {
    fn new_impl(root: &str) -> Result<Self, TailwindCssError> {
        Ok(Self {
            candidate_cache: None,
            root: normalize_root_path(root)?,
            tailwind_module_url: None,
        })
    }

    fn prepare_transform(
        &mut self,
        code: &str,
        module_id: &str,
    ) -> Result<PreparedTransformData, TailwindCssError> {
        let importer_dir = importer_dir_for_module(module_id, &self.root);
        let css = expand_css_imports(code, &importer_dir, &self.root)?;
        let candidates = self.collect_candidates()?;
        let tailwind_module_url = if let Some(url) = &self.tailwind_module_url {
            url.clone()
        } else {
            let url = resolve_tailwind_module_url(&self.root)?;
            self.tailwind_module_url = Some(url.clone());
            url
        };

        Ok(PreparedTransformData {
            candidates,
            css,
            tailwind_module_url,
        })
    }

    fn collect_candidates(&mut self) -> Result<Vec<String>, TailwindCssError> {
        let snapshot = build_candidate_snapshot(&self.root)?;
        if let Some(cache) = &self.candidate_cache
            && cache.files == snapshot
        {
            return Ok(cache.candidates.clone());
        }

        let candidates = scan_candidates(&snapshot);
        self.candidate_cache = Some(CandidateCache {
            candidates: candidates.clone(),
            files: snapshot,
        });
        Ok(candidates)
    }
}

#[cfg(not(test))]
#[pymethods]
impl TailwindCssTransformer {
    #[new]
    fn new(root: &str) -> PyResult<Self> {
        Self::new_impl(root).map_err(TailwindCssError::into_pyerr)
    }

    fn prepare(&mut self, code: &str, module_id: &str) -> PyResult<PreparedTransform> {
        self.prepare_transform(code, module_id)
            .map(PreparedTransform::from)
            .map_err(TailwindCssError::into_pyerr)
    }
}

fn normalize_root_path(root: &str) -> Result<PathBuf, TailwindCssError> {
    let raw = PathBuf::from(root);
    let absolute = if raw.is_absolute() {
        raw
    } else {
        std::env::current_dir()
            .map_err(|err| TailwindCssError::Runtime(err.to_string()))?
            .join(raw)
    };

    Ok(canonicalize_if_exists(absolute))
}

fn canonicalize_if_exists(path: PathBuf) -> PathBuf {
    fs::canonicalize(&path).unwrap_or(path)
}

fn importer_dir_for_module(module_id: &str, root: &Path) -> PathBuf {
    let raw = Path::new(module_id);
    let path = if raw.is_absolute() {
        raw.to_path_buf()
    } else {
        root.join(raw)
    };
    let path = canonicalize_if_exists(path);

    if path.is_dir() {
        return path;
    }

    if path.extension().is_some() {
        return path
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_else(|| path.clone());
    }

    path
}

fn build_candidate_snapshot(root: &Path) -> Result<Vec<CandidateFileStamp>, TailwindCssError> {
    let mut files = Vec::new();
    let walker = WalkDir::new(root)
        .sort_by_file_name()
        .into_iter()
        .filter_entry(should_visit_entry);

    for entry in walker {
        let entry = entry.map_err(|err| TailwindCssError::Runtime(err.to_string()))?;
        if !entry.file_type().is_file() {
            continue;
        }

        let path = entry.path();
        if !should_scan_file(path) {
            continue;
        }

        let modified_ms = entry
            .metadata()
            .ok()
            .and_then(|metadata| metadata.modified().ok())
            .and_then(|modified| modified.duration_since(UNIX_EPOCH).ok())
            .map(|duration| duration.as_millis());

        files.push(CandidateFileStamp {
            modified_ms,
            path: path.to_path_buf(),
        });
    }

    Ok(files)
}

fn should_visit_entry(entry: &DirEntry) -> bool {
    if entry.depth() == 0 || !entry.file_type().is_dir() {
        return true;
    }

    let Some(name) = entry.file_name().to_str() else {
        return true;
    };
    !IGNORED_DIRECTORIES.contains(&name)
}

fn should_scan_file(path: &Path) -> bool {
    let Some(extension) = path.extension().and_then(|value| value.to_str()) else {
        return false;
    };
    CONTENT_EXTENSIONS.contains(&extension.to_ascii_lowercase().as_str())
}

fn scan_candidates(snapshot: &[CandidateFileStamp]) -> Vec<String> {
    let mut candidates = BTreeSet::new();

    for stamp in snapshot {
        let Ok(source) = fs::read_to_string(&stamp.path) else {
            continue;
        };

        for token in CANDIDATE_PATTERN.find_iter(&source).map(|capture| capture.as_str()) {
            if is_likely_candidate(token) {
                candidates.insert(token.to_owned());
            }
        }
    }

    candidates.into_iter().collect()
}

fn is_likely_candidate(token: &str) -> bool {
    if token.is_empty() || token.len() > MAX_TOKEN_LEN {
        return false;
    }

    if token.starts_with('.') || token.starts_with('/') || token.starts_with('@') {
        return false;
    }

    if token.contains("://")
        || token.ends_with(".tsx")
        || token.ends_with(".ts")
        || token.ends_with(".jsx")
        || token.ends_with(".js")
    {
        return false;
    }

    token.chars().any(|char| matches!(char, '-' | ':' | '[' | ']' | '/')) || token == "flex" || token == "grid"
}

fn expand_css_imports(
    css: &str,
    importer_dir: &Path,
    root: &Path,
) -> Result<String, TailwindCssError> {
    let mut stack = Vec::new();
    expand_css_imports_inner(css, importer_dir, root, &mut stack)
}

fn expand_css_imports_inner(
    css: &str,
    importer_dir: &Path,
    root: &Path,
    stack: &mut Vec<PathBuf>,
) -> Result<String, TailwindCssError> {
    let mut output = String::new();
    let mut position = 0;

    for captures in CSS_IMPORT_PATTERN.captures_iter(css) {
        let Some(matched) = captures.get(0) else {
            continue;
        };
        output.push_str(&css[position..matched.start()]);

        let specifier = captures
            .get(1)
            .or_else(|| captures.get(2))
            .map(|capture| capture.as_str().trim())
            .unwrap_or("");

        if specifier.is_empty() {
            output.push_str(matched.as_str());
            position = matched.end();
            continue;
        }

        let resolved = resolve_css_import_path(specifier, importer_dir, root).map_err(|err| {
            TailwindCssError::Runtime(format!("failed to resolve @import \"{specifier}\": {err}"))
        })?;

        if stack.contains(&resolved) {
            output.push_str(&format!("/* circular @import skipped: {} */", resolved.display()));
            position = matched.end();
            continue;
        }

        stack.push(resolved.clone());
        let inner = fs::read_to_string(&resolved).map_err(|err| {
            TailwindCssError::Runtime(format!("failed to resolve @import \"{specifier}\": {err}"))
        })?;
        let expanded = expand_css_imports_inner(&inner, resolved.parent().unwrap_or(importer_dir), root, stack)?;
        stack.pop();
        output.push_str(&expanded);
        position = matched.end();
    }

    output.push_str(&css[position..]);
    Ok(output)
}

fn resolve_css_import_path(
    specifier: &str,
    importer_dir: &Path,
    root: &Path,
) -> Result<PathBuf, TailwindCssError> {
    if is_relative_specifier(specifier) {
        let path = importer_dir.join(specifier);
        return resolve_existing_file(
            path,
            format!("CSS import not found: {specifier} (from {})", importer_dir.display()),
        );
    }

    let absolute = PathBuf::from(specifier);
    if absolute.is_absolute() {
        return resolve_existing_file(absolute.clone(), format!("CSS import not found: {}", absolute.display()));
    }

    let Some((package_name, subpath)) = split_package_specifier(specifier) else {
        return Err(TailwindCssError::Runtime(format!(
            "failed to resolve css import \"{specifier}\""
        )));
    };

    let Some(package_dir) = find_node_modules_package_dir(&package_name, importer_dir, root) else {
        return Err(TailwindCssError::FileNotFound(format!(
            "failed to resolve css import \"{specifier}\""
        )));
    };

    if let Some(subpath) = &subpath {
        let candidate = package_dir.join(subpath);
        if let Ok(path) = resolve_existing_file(candidate, String::new()) {
            return Ok(path);
        }
    }

    resolve_package_style_export(&package_dir, specifier, subpath.as_deref())
}

fn is_relative_specifier(specifier: &str) -> bool {
    specifier.starts_with("./") || specifier.starts_with("../")
}

fn split_package_specifier(specifier: &str) -> Option<(String, Option<String>)> {
    if is_relative_specifier(specifier) || Path::new(specifier).is_absolute() {
        return None;
    }

    if let Some(rest) = specifier.strip_prefix('@') {
        let (scope, rest) = rest.split_once('/')?;
        return if let Some((name, subpath)) = rest.split_once('/') {
            Some((format!("@{scope}/{name}"), Some(subpath.to_owned())))
        } else {
            Some((format!("@{scope}/{rest}"), None))
        };
    }

    if let Some((name, subpath)) = specifier.split_once('/') {
        Some((name.to_owned(), Some(subpath.to_owned())))
    } else {
        Some((specifier.to_owned(), None))
    }
}

fn find_node_modules_package_dir(package_name: &str, importer_dir: &Path, root: &Path) -> Option<PathBuf> {
    let mut current = canonicalize_if_exists(importer_dir.to_path_buf());
    let root = canonicalize_if_exists(root.to_path_buf());

    loop {
        let candidate = package_dir_in_node_modules(&current, package_name);
        if candidate.is_dir() {
            return Some(canonicalize_if_exists(candidate));
        }

        if current == root {
            break;
        }

        let Some(parent) = current.parent() else {
            break;
        };
        if parent == current {
            break;
        }
        current = parent.to_path_buf();
    }

    None
}

fn package_dir_in_node_modules(base: &Path, package_name: &str) -> PathBuf {
    let mut path = base.join("node_modules");
    for part in package_name.split('/') {
        path.push(part);
    }
    path
}

fn resolve_package_style_export(
    package_dir: &Path,
    specifier: &str,
    subpath: Option<&str>,
) -> Result<PathBuf, TailwindCssError> {
    let package_json = read_package_json(package_dir)?;
    let export_key = subpath.map_or_else(|| ".".to_owned(), |value| format!("./{value}"));
    let Some(exports) = package_json.get("exports").and_then(Value::as_object) else {
        return Err(TailwindCssError::Runtime(format!(
            "package \"{specifier}\" has no exports map"
        )));
    };
    let Some(export_entry) = exports.get(&export_key) else {
        return Err(TailwindCssError::Runtime(format!(
            "package \"{specifier}\" does not define exports[\"{export_key}\"]"
        )));
    };

    let style_path = if let Some(value) = export_entry.as_str() {
        Some(value.to_owned())
    } else if let Some(mapping) = export_entry.as_object() {
        mapping
            .get("style")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned)
            .or_else(|| {
                package_json
                    .get("style")
                    .and_then(Value::as_str)
                    .map(ToOwned::to_owned)
            })
    } else {
        None
    };

    let Some(style_path) = style_path else {
        return Err(TailwindCssError::Runtime(format!(
            "package \"{specifier}\" does not define a style export for \"{export_key}\""
        )));
    };

    let path = package_dir.join(style_path);
    resolve_existing_file(path.clone(), format!("resolved style file missing: {}", path.display()))
}

fn resolve_tailwind_module_url(root: &Path) -> Result<String, TailwindCssError> {
    let path = resolve_package_entry(root, "tailwindcss")?;
    if !path.is_file() {
        return Err(TailwindCssError::FileNotFound(format!(
            "tailwindcss entry is not a file: {}",
            path.display()
        )));
    }

    Url::from_file_path(&path)
        .map(|url| url.to_string())
        .map_err(|_| TailwindCssError::Runtime(format!("failed to convert path to file URL: {}", path.display())))
}

fn resolve_package_entry(root: &Path, package_name: &str) -> Result<PathBuf, TailwindCssError> {
    let mut package_dirs = vec![package_dir_in_node_modules(root, package_name)];
    if package_name == "tailwindcss" {
        package_dirs.push(
            root.join("node_modules")
                .join("@tailwindcss")
                .join("vite")
                .join("node_modules")
                .join("tailwindcss"),
        );
    }

    for package_dir in package_dirs {
        let Ok(package_json) = read_package_json(&package_dir) else {
            continue;
        };
        if let Ok(path) = package_main_file(&package_dir, &package_json) {
            return Ok(path);
        }
    }

    Err(TailwindCssError::FileNotFound(format!(
        "Cannot find module '{package_name}' under {}",
        root.display()
    )))
}

fn read_package_json(package_dir: &Path) -> Result<Value, TailwindCssError> {
    let path = package_dir.join("package.json");
    let contents = fs::read_to_string(&path)
        .map_err(|err| TailwindCssError::Runtime(format!("failed to read {}: {err}", path.display())))?;
    serde_json::from_str(&contents)
        .map_err(|err| TailwindCssError::Runtime(format!("failed to parse {}: {err}", path.display())))
}

fn package_main_file(package_dir: &Path, package_json: &Value) -> Result<PathBuf, TailwindCssError> {
    let exported = package_json.get("exports").and_then(|value| value.get("."));
    if let Some(value) = exported.and_then(Value::as_str) {
        return resolve_existing_file(package_dir.join(value), String::new());
    }

    if let Some(mapping) = exported.and_then(Value::as_object) {
        for key in ["import", "default"] {
            if let Some(value) = mapping.get(key).and_then(Value::as_str) {
                return resolve_existing_file(package_dir.join(value), String::new());
            }
        }
    }

    for key in ["module", "main"] {
        if let Some(value) = package_json.get(key).and_then(Value::as_str) {
            return resolve_existing_file(package_dir.join(value), String::new());
        }
    }

    resolve_existing_file(package_dir.join("index.js"), String::new())
}

fn resolve_existing_file(path: PathBuf, message: String) -> Result<PathBuf, TailwindCssError> {
    if path.is_file() {
        return Ok(canonicalize_if_exists(path));
    }

    let message = if message.is_empty() {
        format!("file not found: {}", path.display())
    } else {
        message
    };
    Err(TailwindCssError::FileNotFound(message))
}

#[cfg(not(test))]
#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PreparedTransform>()?;
    m.add_class::<TailwindCssTransformer>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::{thread, time::Duration};

    use tempfile::TempDir;

    use super::*;

    fn write(path: &Path, contents: &str) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("parent directories should be created");
        }
        fs::write(path, contents).expect("file should be written");
    }

    fn write_tailwind_package(root: &Path) {
        write(
            &root.join("node_modules/tailwindcss/package.json"),
            r#"{"name":"tailwindcss","type":"module","exports":{".":{"import":"./index.mjs","style":"./theme.css"}}}"#,
        );
        write(
            &root.join("node_modules/tailwindcss/index.mjs"),
            "export async function compile(source) { return { build() { return source; } }; }\n",
        );
        write(&root.join("node_modules/tailwindcss/theme.css"), "@layer theme, base, components, utilities;\n");
    }

    #[test]
    fn prepare_transform_expands_imports_and_collects_candidates() {
        let temp_dir = TempDir::new().expect("temp dir should exist");
        let root = temp_dir.path();
        write_tailwind_package(root);
        write(&root.join("package.json"), "{}\n");
        write(&root.join("styles/other.css"), ".nested { color: red; }\n");
        write(
            &root.join("widgets/todo/widget.tsx"),
            "export default function App() { return <div className=\"mx-auto\" />; }\n",
        );

        let mut transformer = TailwindCssTransformer::new_impl(&root.display().to_string())
            .expect("transformer should initialize");
        let prepared = transformer
            .prepare_transform("@import \"./other.css\";\n", "styles/app.css")
            .expect("prepare should succeed");

        assert!(prepared.css.contains(".nested"));
        assert!(prepared.candidates.iter().any(|candidate| candidate == "mx-auto"));
        assert!(prepared.tailwind_module_url.starts_with("file://"));
    }

    #[test]
    fn collect_candidates_invalidates_cache_after_file_change() {
        let temp_dir = TempDir::new().expect("temp dir should exist");
        let root = temp_dir.path();
        write_tailwind_package(root);
        write(&root.join("package.json"), "{}\n");
        let widget_path = root.join("widgets/todo/widget.tsx");
        write(
            &widget_path,
            "export default function App() { return <div className=\"mx-auto\" />; }\n",
        );

        let mut transformer = TailwindCssTransformer::new_impl(&root.display().to_string())
            .expect("transformer should initialize");
        let first = transformer
            .prepare_transform("@import \"tailwindcss\";\n", "styles/app.css")
            .expect("first prepare should succeed");
        assert!(first.candidates.iter().any(|candidate| candidate == "mx-auto"));

        thread::sleep(Duration::from_millis(20));
        write(
            &widget_path,
            "export default function App() { return <div className=\"grid\" />; }\n",
        );

        let second = transformer
            .prepare_transform("@import \"tailwindcss\";\n", "styles/app.css")
            .expect("second prepare should succeed");
        assert!(second.candidates.iter().any(|candidate| candidate == "grid"));
        assert!(!second.candidates.iter().any(|candidate| candidate == "mx-auto"));
    }
}
