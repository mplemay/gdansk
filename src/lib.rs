mod bundle;

use pyo3::prelude::*;

#[pyfunction]
fn hello_from_bin() -> String {
    "Hello from gdansk!".to_string()
}

#[pymodule]
fn _core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(hello_from_bin, module)?)?;
    bundle::register(module)?;
    Ok(())
}
