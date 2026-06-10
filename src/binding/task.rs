use std::path::PathBuf;

use pyo3::prelude::*;

use crate::{
    binding::task_options::PyRunTaskOptions,
    binding::task_process::PyTaskProcess,
    exceptions::GdanskRuntimeError,
    task::TaskRunner,
    types::error::BindingError,
    utils::normalize_task_options::{ensure_task_success, normalize_run_task_options},
    utils::py_error,
};

#[pyclass(name = "TaskRunner", module = "gdansk._core")]
#[derive(Debug, Default)]
pub(crate) struct PyTaskRunner;

#[pymethods]
impl PyTaskRunner {
    #[new]
    fn new() -> Self {
        Self
    }

    fn run<'py>(
        &self,
        py: Python<'py>,
        options: PyRef<'_, PyRunTaskOptions>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let normalized = normalized_options_from_py(options)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let result = tokio::task::spawn_blocking(move || TaskRunner.run_blocking(normalized))
                .await
                .map_err(|error| GdanskRuntimeError::new_err(format!("Task run failed: {error}")))?
                .map_err(|error| BindingError::runtime(error.to_string()))
                .map_err(py_error::from_binding_error)?;
            ensure_task_success(result).map_err(py_error::from_binding_error)
        })
    }

    fn start<'py>(
        &self,
        py: Python<'py>,
        options: PyRef<'_, PyRunTaskOptions>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let normalized = normalized_options_from_py(options)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            tokio::task::spawn_blocking(move || TaskRunner.start_blocking(normalized))
                .await
                .map_err(|error| {
                    GdanskRuntimeError::new_err(format!("Task start failed: {error}"))
                })?
                .map_err(|error| BindingError::runtime(error.to_string()))
                .map_err(py_error::from_binding_error)
                .map(PyTaskProcess::new)
        })
    }

    fn __repr__(&self) -> &'static str {
        "TaskRunner()"
    }
}

fn normalized_options_from_py(
    options: PyRef<'_, PyRunTaskOptions>,
) -> PyResult<crate::task::RunTaskOptions> {
    let task_cwd = PathBuf::from(&options.task_cwd);
    normalize_run_task_options(
        task_cwd,
        options.script.clone(),
        options.argv.clone(),
        options.env.clone(),
        options.host.clone(),
        options.port,
    )
    .map_err(py_error::from_binding_error)
}
