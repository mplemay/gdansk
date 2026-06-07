mod binding;
mod embed;
mod exceptions;
mod frontend;
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
    m.add_class::<binding::PyFrontendDevServer>()?;
    m.add_function(wrap_pyfunction!(binding::py_install_packages, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_lock_packages, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_update_packages, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_ainstall_packages, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_alock_packages, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_aupdate_packages, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_build_frontend, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_start_frontend_dev, m)?)?;
    m.add("GdanskError", py.get_type::<exceptions::GdanskError>())?;
    m.add(
        "GdanskRuntimeError",
        py.get_type::<exceptions::GdanskRuntimeError>(),
    )?;
    m.add(
        "GdanskModuleError",
        py.get_type::<exceptions::GdanskModuleError>(),
    )?;
    m.add(
        "GdanskJavaScriptError",
        py.get_type::<exceptions::GdanskJavaScriptError>(),
    )?;
    Ok(())
}
