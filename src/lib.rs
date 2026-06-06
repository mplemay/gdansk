mod binding;
mod exceptions;
mod options;
mod packages;
mod runtime;
mod script;
mod types;
mod utils;

use pyo3::prelude::*;

/// A Python module implemented in Rust. The name of this module must match
/// the `lib.name` setting in the `Cargo.toml`, else Python will not be able to
/// import the module.
#[pymodule]
fn _core(py: Python<'_>, m: &pyo3::Bound<'_, pyo3::types::PyModule>) -> pyo3::PyResult<()> {
    m.add_class::<binding::PyScript>()?;
    m.add_class::<binding::PyRuntime>()?;
    m.add_class::<binding::PyRuntimeOptions>()?;
    m.add_class::<binding::PySyncRunner>()?;
    m.add_class::<binding::PyAsyncRunner>()?;
    m.add_class::<binding::PyPackageInstallResult>()?;
    m.add_class::<binding::PyPackageUpdateChange>()?;
    m.add_class::<binding::PyPackageUpdateResult>()?;
    m.add_function(wrap_pyfunction!(binding::py_install_packages, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_lock_packages, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_update_packages, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_ainstall_packages, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_alock_packages, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_aupdate_packages, m)?)?;
    m.add("DenoError", py.get_type::<exceptions::DenoError>())?;
    m.add(
        "DenoRuntimeError",
        py.get_type::<exceptions::DenoRuntimeError>(),
    )?;
    m.add(
        "DenoModuleError",
        py.get_type::<exceptions::DenoModuleError>(),
    )?;
    m.add(
        "DenoJavaScriptError",
        py.get_type::<exceptions::DenoJavaScriptError>(),
    )?;
    Ok(())
}
