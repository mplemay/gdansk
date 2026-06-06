use std::path::PathBuf;

use pyo3::{Bound, PyAny, PyResult, Python, pyclass, pyfunction, pymethods, types::PyAnyMethods};

use crate::{exceptions::DenoRuntimeError, packages, utils::normalize_path};

#[pyclass(
    name = "PackageInstallResult",
    module = "gdansk._core",
    skip_from_py_object
)]
#[derive(Clone, Debug)]
pub struct PyPackageInstallResult {
    lockfile: PathBuf,
    dependencies: usize,
    dev_dependencies: usize,
}

#[pymethods]
impl PyPackageInstallResult {
    #[getter]
    fn lockfile(&self) -> String {
        self.lockfile.to_string_lossy().into_owned()
    }

    #[getter]
    fn dependencies(&self) -> usize {
        self.dependencies
    }

    #[getter]
    fn dev_dependencies(&self) -> usize {
        self.dev_dependencies
    }

    fn __repr__(&self) -> String {
        format!(
            "PackageInstallResult(lockfile={:?}, dependencies={}, dev_dependencies={})",
            self.lockfile(),
            self.dependencies,
            self.dev_dependencies,
        )
    }
}

#[pyclass(
    name = "PackageUpdateChange",
    module = "gdansk._core",
    skip_from_py_object
)]
#[derive(Clone, Debug)]
pub struct PyPackageUpdateChange {
    name: String,
    previous: String,
    updated: String,
}

#[pymethods]
impl PyPackageUpdateChange {
    #[getter]
    fn name(&self) -> &str {
        &self.name
    }

    #[getter]
    fn previous(&self) -> &str {
        &self.previous
    }

    #[getter]
    fn updated(&self) -> &str {
        &self.updated
    }

    fn __repr__(&self) -> String {
        format!(
            "PackageUpdateChange(name={:?}, previous={:?}, updated={:?})",
            self.name, self.previous, self.updated
        )
    }
}

#[pyclass(
    name = "PackageUpdateResult",
    module = "gdansk._core",
    skip_from_py_object
)]
#[derive(Clone, Debug)]
pub struct PyPackageUpdateResult {
    lockfile: PathBuf,
    changes: Vec<PyPackageUpdateChange>,
}

#[pymethods]
impl PyPackageUpdateResult {
    #[getter]
    fn lockfile(&self) -> String {
        self.lockfile.to_string_lossy().into_owned()
    }

    #[getter]
    fn changes(&self) -> Vec<PyPackageUpdateChange> {
        self.changes.clone()
    }

    fn __repr__(&self) -> String {
        format!(
            "PackageUpdateResult(lockfile={:?}, changes={})",
            self.lockfile(),
            self.changes.len(),
        )
    }
}

#[pyfunction(name = "install_packages", signature = (cwd = None, *, include_dev = true, lockfile_only = false))]
pub fn py_install_packages(
    py: Python<'_>,
    cwd: Option<&Bound<'_, PyAny>>,
    include_dev: bool,
    lockfile_only: bool,
) -> PyResult<PyPackageInstallResult> {
    let cwd = normalize_path::normalize_cwd(py, cwd)?;
    py.detach(|| {
        pyo3_async_runtimes::tokio::get_runtime().block_on(packages::install_packages(
            cwd,
            include_dev,
            lockfile_only,
        ))
    })
    .map(Into::into)
    .map_err(package_error_to_py)
}

#[pyfunction(name = "lock_packages", signature = (cwd = None, *, include_dev = true))]
pub fn py_lock_packages(
    py: Python<'_>,
    cwd: Option<&Bound<'_, PyAny>>,
    include_dev: bool,
) -> PyResult<PyPackageInstallResult> {
    let cwd = normalize_path::normalize_cwd(py, cwd)?;
    py.detach(|| {
        pyo3_async_runtimes::tokio::get_runtime()
            .block_on(packages::lock_packages(cwd, include_dev))
    })
    .map(Into::into)
    .map_err(package_error_to_py)
}

#[pyfunction(name = "update_packages", signature = (cwd = None, packages = None, *, include_dev = true, latest = false, lockfile_only = false))]
pub fn py_update_packages(
    py: Python<'_>,
    cwd: Option<&Bound<'_, PyAny>>,
    packages: Option<&Bound<'_, PyAny>>,
    include_dev: bool,
    latest: bool,
    lockfile_only: bool,
) -> PyResult<PyPackageUpdateResult> {
    let cwd = normalize_path::normalize_cwd(py, cwd)?;
    let filters = normalize_package_filters(packages)?;
    py.detach(|| {
        pyo3_async_runtimes::tokio::get_runtime().block_on(packages::update_packages(
            cwd,
            filters,
            include_dev,
            latest,
            lockfile_only,
        ))
    })
    .map(Into::into)
    .map_err(package_error_to_py)
}

#[pyfunction(name = "ainstall_packages", signature = (cwd = None, *, include_dev = true, lockfile_only = false))]
pub fn py_ainstall_packages<'py>(
    py: Python<'py>,
    cwd: Option<&Bound<'_, PyAny>>,
    include_dev: bool,
    lockfile_only: bool,
) -> PyResult<Bound<'py, PyAny>> {
    let cwd = normalize_path::normalize_cwd(py, cwd)?;
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        let result = run_packages_on_blocking_thread(move || {
            pyo3_async_runtimes::tokio::get_runtime().block_on(packages::install_packages(
                cwd,
                include_dev,
                lockfile_only,
            ))
        })
        .await?;
        Ok(PyPackageInstallResult::from(result))
    })
}

#[pyfunction(name = "alock_packages", signature = (cwd = None, *, include_dev = true))]
pub fn py_alock_packages<'py>(
    py: Python<'py>,
    cwd: Option<&Bound<'_, PyAny>>,
    include_dev: bool,
) -> PyResult<Bound<'py, PyAny>> {
    let cwd = normalize_path::normalize_cwd(py, cwd)?;
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        let result = run_packages_on_blocking_thread(move || {
            pyo3_async_runtimes::tokio::get_runtime()
                .block_on(packages::lock_packages(cwd, include_dev))
        })
        .await?;
        Ok(PyPackageInstallResult::from(result))
    })
}

#[pyfunction(name = "aupdate_packages", signature = (cwd = None, packages = None, *, include_dev = true, latest = false, lockfile_only = false))]
pub fn py_aupdate_packages<'py>(
    py: Python<'py>,
    cwd: Option<&Bound<'_, PyAny>>,
    packages: Option<&Bound<'_, PyAny>>,
    include_dev: bool,
    latest: bool,
    lockfile_only: bool,
) -> PyResult<Bound<'py, PyAny>> {
    let cwd = normalize_path::normalize_cwd(py, cwd)?;
    let filters = normalize_package_filters(packages)?;
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        let result = run_packages_on_blocking_thread(move || {
            pyo3_async_runtimes::tokio::get_runtime().block_on(packages::update_packages(
                cwd,
                filters,
                include_dev,
                latest,
                lockfile_only,
            ))
        })
        .await?;
        Ok(PyPackageUpdateResult::from(result))
    })
}

async fn run_packages_on_blocking_thread<T, F>(operation: F) -> PyResult<T>
where
    T: Send + 'static,
    F: FnOnce() -> Result<T, deno_core::error::AnyError> + Send + 'static,
{
    tokio::task::spawn_blocking(operation)
        .await
        .map_err(|error| {
            DenoRuntimeError::new_err(format!("Deno package operation failed: {error}"))
        })?
        .map_err(package_error_to_py)
}

fn normalize_package_filters(packages: Option<&Bound<'_, PyAny>>) -> PyResult<Vec<String>> {
    match packages {
        Some(value) if !value.is_none() => value.extract(),
        _ => Ok(Vec::new()),
    }
}

fn package_error_to_py(error: deno_core::error::AnyError) -> pyo3::PyErr {
    DenoRuntimeError::new_err(error.to_string())
}

impl From<packages::PackageInstallResult> for PyPackageInstallResult {
    fn from(value: packages::PackageInstallResult) -> Self {
        Self {
            lockfile: value.lockfile,
            dependencies: value.dependencies,
            dev_dependencies: value.dev_dependencies,
        }
    }
}

impl From<packages::PackageUpdateResult> for PyPackageUpdateResult {
    fn from(value: packages::PackageUpdateResult) -> Self {
        Self {
            lockfile: value.lockfile,
            changes: value.changes.into_iter().map(Into::into).collect(),
        }
    }
}

impl From<packages::PackageUpdateChange> for PyPackageUpdateChange {
    fn from(value: packages::PackageUpdateChange) -> Self {
        Self {
            name: value.name,
            previous: value.previous,
            updated: value.updated,
        }
    }
}
