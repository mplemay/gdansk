use pyo3::prelude::*;

#[pymodule]
mod _core {
    use pyo3::prelude::*;

    #[pyfunction]
    fn hello_from_bin() -> String {
        "Hello from gdansk!".to_string()
    }

    #[pyfunction]
    fn rust_sleep(py: Python) -> PyResult<Bound<PyAny>> {
        pyo3_async_runtimes::tokio::future_into_py(py, async {
            tokio::time::sleep(std::time::Duration::from_secs(1)).await;
            Ok(())
        })
    }
}
