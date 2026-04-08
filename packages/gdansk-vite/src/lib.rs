mod runtime;

use pyo3::{
    exceptions::{PyRuntimeError, PyValueError},
    prelude::*,
};

#[cfg(test)]
mod test_support {
    use std::sync::{Mutex, OnceLock};

    pub(crate) fn js_runtime_lock() -> &'static Mutex<()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
    }
}

#[pyfunction]
fn transform_assets_json(specs_json: &str, root: &str, assets_json: &str) -> PyResult<String> {
    let specs: Vec<runtime::VitePluginSpec> = serde_json::from_str(specs_json)
        .map_err(|err| PyValueError::new_err(format!("invalid Vite plugin payload: {err}")))?;
    let assets: Vec<runtime::PluginAssetInput> = serde_json::from_str(assets_json)
        .map_err(|err| PyValueError::new_err(format!("invalid CSS asset payload: {err}")))?;
    let result = runtime::run_embedded_vite_plugins(&specs, std::path::Path::new(root), assets)
        .map_err(|err| PyRuntimeError::new_err(err.to_string()))?;
    serde_json::to_string(&result).map_err(|err| {
        PyRuntimeError::new_err(format!("failed to encode Vite transform result: {err}"))
    })
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(transform_assets_json, m)?)?;
    Ok(())
}
