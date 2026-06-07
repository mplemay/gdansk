use std::sync::Arc;

use pyo3::prelude::*;

use crate::{exceptions::GdanskRuntimeError, task::TaskProcess};

#[pyclass(name = "TaskProcess", module = "gdansk._core")]
pub(crate) struct PyTaskProcess {
    inner: Arc<TaskProcess>,
}

impl PyTaskProcess {
    pub(crate) fn new(process: TaskProcess) -> Self {
        Self {
            inner: Arc::new(process),
        }
    }
}

#[pymethods]
impl PyTaskProcess {
    #[getter]
    fn origin(&self) -> String {
        self.inner.origin().to_string()
    }

    fn stop<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let process = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            tokio::task::spawn_blocking(move || process.stop_blocking())
                .await
                .map_err(|error| GdanskRuntimeError::new_err(format!("Task stop failed: {error}")))?
                .map_err(|error| GdanskRuntimeError::new_err(error.to_string()))
        })
    }

    fn __repr__(&self) -> String {
        format!("TaskProcess(origin={:?})", self.inner.origin())
    }
}
