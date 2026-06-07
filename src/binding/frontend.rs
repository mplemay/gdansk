use std::sync::Arc;

use pyo3::{Bound, PyAny, PyResult, Python, pyclass, pyfunction, pymethods};

use crate::{exceptions::GdanskRuntimeError, frontend, utils::normalize_path};

#[pyclass(module = "gdansk._core", name = "FrontendDevServer")]
pub(crate) struct PyFrontendDevServer {
    inner: Arc<frontend::FrontendDevServer>,
}

impl PyFrontendDevServer {
    fn new(server: frontend::FrontendDevServer) -> Self {
        Self {
            inner: Arc::new(server),
        }
    }
}

#[pymethods]
impl PyFrontendDevServer {
    #[getter]
    fn origin(&self) -> String {
        self.inner.origin().to_string()
    }

    fn stop<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let server = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            tokio::task::spawn_blocking(move || server.stop_blocking())
                .await
                .map_err(|error| {
                    GdanskRuntimeError::new_err(format!(
                        "Embedded Vite dev-server stop task failed: {error}"
                    ))
                })?
                .map_err(|error| GdanskRuntimeError::new_err(error.to_string()))
        })
    }
}

#[pyfunction(name = "build_frontend", signature = (root, build_directory))]
pub fn py_build_frontend<'py>(
    py: Python<'py>,
    root: &Bound<'py, PyAny>,
    build_directory: String,
) -> PyResult<Bound<'py, PyAny>> {
    let root = normalize_path::path_from_py(root, "root")?;
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        tokio::task::spawn_blocking(move || {
            frontend::build_frontend_blocking(root, build_directory)
        })
        .await
        .map_err(|error| {
            GdanskRuntimeError::new_err(format!("Embedded Vite build task failed: {error}"))
        })?
        .map_err(|error| GdanskRuntimeError::new_err(error.to_string()))
    })
}

#[pyfunction(name = "start_frontend_dev", signature = (root, host, port))]
pub fn py_start_frontend_dev<'py>(
    py: Python<'py>,
    root: &Bound<'py, PyAny>,
    host: String,
    port: u16,
) -> PyResult<Bound<'py, PyAny>> {
    let root = normalize_path::path_from_py(root, "root")?;
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        tokio::task::spawn_blocking(move || frontend::start_frontend_dev(root, host, port))
            .await
            .map_err(|error| {
                GdanskRuntimeError::new_err(format!(
                    "Embedded Vite dev-server start task failed: {error}"
                ))
            })?
            .map(PyFrontendDevServer::new)
            .map_err(|error| GdanskRuntimeError::new_err(error.to_string()))
    })
}
