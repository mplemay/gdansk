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
use rolldown::{Bundler, BundlerOptions, ExperimentalOptions, InputItem};
#[cfg(not(test))]
use rolldown_dev::{BundlerConfig, DevEngine, DevOptions, RebuildStrategy};
#[cfg(not(test))]
use std::sync::Arc;

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

#[cfg(not(test))]
struct DevEngineCloseGuard {
    engine: Option<Arc<DevEngine>>,
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
#[pymodule]
mod _core {
    use super::*;

    #[pyfunction(signature = (paths, dev = false, minify = true, output = None, cwd = None))]
    fn bundle(
        py: Python<'_>,
        paths: HashSet<PathBuf>,
        dev: bool,
        minify: bool,
        output: Option<PathBuf>,
        cwd: Option<PathBuf>,
    ) -> PyResult<Bound<'_, PyAny>> {
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let cwd = match cwd {
                Some(dir) => dunce::simplified(
                    &dir.canonicalize()
                        .map_err(|err| py_runtime_error("failed to resolve provided cwd", err))?,
                )
                .to_path_buf(),
                None => std::env::current_dir().map_err(|err| {
                    py_runtime_error("failed to read current working directory", err)
                })?,
            };
            let output_dir = output.unwrap_or_else(|| PathBuf::from(".gdansk"));
            let output_dir_string =
                path_to_utf8(&output_dir, "output path").map_err(map_bundle_error)?;

            let normalized =
                normalize_inputs(paths, &cwd, &output_dir).map_err(map_bundle_error)?;
            let input_items = normalized
                .into_iter()
                .map(|item| InputItem {
                    name: Some(item.name),
                    import: item.import,
                })
                .collect::<Vec<_>>();

            let mut options = BundlerOptions {
                input: Some(input_items),
                cwd: Some(cwd),
                dir: Some(output_dir_string),
                entry_filenames: Some("[name].js".to_string().into()),
                css_entry_filenames: Some("[name].css".to_string().into()),
                minify: Some(minify.into()),
                ..Default::default()
            };

            if dev {
                options.experimental = Some(ExperimentalOptions {
                    incremental_build: Some(true),
                    ..Default::default()
                });
            }

            if dev {
                let bundler_config = BundlerConfig::new(options, vec![]);
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
                let mut bundler = Bundler::new(options)
                    .map_err(|err| py_runtime_error("failed to initialize Bundler", err))?;
                bundler
                    .write()
                    .await
                    .map_err(|err| py_runtime_error("bundling failed", err))?;
                Ok(())
            }
        })
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
}
