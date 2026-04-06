use pyo3::{exceptions::PyTypeError, prelude::*, types::PyList};
use rolldown_plugin::__inner::SharedPluginable;

use super::py_plugin::parse_plugin_item;

pub(crate) fn parse_plugins(plugins: Option<&Bound<'_, PyAny>>) -> PyResult<Vec<SharedPluginable>> {
    let Some(plugins) = plugins else {
        return Ok(Vec::new());
    };
    let list = plugins
        .cast::<PyList>()
        .map_err(|_| PyTypeError::new_err("Bundler.plugins must be a list of plugin mappings"))?;
    let mut out = Vec::with_capacity(list.len());
    for item in list.iter() {
        let p = parse_plugin_item(&item)?;
        out.push(p as SharedPluginable);
    }
    Ok(out)
}
