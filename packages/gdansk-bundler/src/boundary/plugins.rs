use pyo3::{exceptions::PyTypeError, prelude::*, types::PySequence};
use rolldown_plugin::__inner::SharedPluginable;

use super::py_plugin::parse_plugin_item;

pub(crate) fn parse_plugins(plugins: Option<&Bound<'_, PyAny>>) -> PyResult<Vec<SharedPluginable>> {
    let Some(plugins) = plugins else {
        return Ok(Vec::new());
    };
    let seq = plugins.cast::<PySequence>().map_err(|_| {
        PyTypeError::new_err("Bundler.plugins must be a sequence of Plugin instances")
    })?;
    let len = seq.len()?;
    let mut out = Vec::with_capacity(len);
    for i in 0..len {
        let item = seq.get_item(i)?;
        let p = parse_plugin_item(&item)?;
        out.push(p as SharedPluginable);
    }
    Ok(out)
}
