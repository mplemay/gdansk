use std::{borrow::Cow, sync::Arc};

use pyo3::{exceptions::PyTypeError, prelude::*, types::PyDict, types::PyString};
use rolldown_plugin::{
    HookResolveIdArgs, HookResolveIdOutput, HookResolveIdReturn, HookUsage, Plugin, PluginContext,
};

use super::parse::{extract_string, get_mapping_item};

#[derive(Debug)]
pub(crate) struct PyPlugin {
    inner: Arc<PyPluginInner>,
}

#[derive(Debug)]
struct PyPluginInner {
    name: String,
    resolve_id: Option<Arc<Py<PyAny>>>,
}

impl PyPlugin {
    pub(crate) fn new(name: String, resolve_id: Option<Arc<Py<PyAny>>>) -> Self {
        Self {
            inner: Arc::new(PyPluginInner { name, resolve_id }),
        }
    }
}

impl Plugin for PyPlugin {
    fn name(&self) -> Cow<'static, str> {
        Cow::Owned(self.inner.name.clone())
    }

    fn resolve_id(
        &self,
        _ctx: &PluginContext,
        args: &HookResolveIdArgs<'_>,
    ) -> impl std::future::Future<Output = HookResolveIdReturn> + Send {
        let inner = Arc::clone(&self.inner);
        let specifier = args.specifier.to_string();
        let importer = args.importer.map(|s| s.to_string());
        async move { resolve_python_resolve_id(&inner, specifier, importer).await }
    }

    fn register_hook_usage(&self) -> HookUsage {
        let mut usage = HookUsage::empty();
        if self.inner.resolve_id.is_some() {
            usage |= HookUsage::ResolveId;
        }
        usage
    }
}

async fn resolve_python_resolve_id(
    inner: &PyPluginInner,
    specifier: String,
    importer: Option<String>,
) -> HookResolveIdReturn {
    let Some(cb) = inner.resolve_id.as_ref().map(Arc::clone) else {
        return Ok(None);
    };
    tokio::task::spawn_blocking(move || {
        Python::attach(|py| {
            let bound = cb.bind(py);
            let out = bound
                .call1((specifier, importer))
                .map_err(|e| anyhow::anyhow!("{}", e))?;
            parse_resolve_bound(&out)
        })
    })
    .await
    .map_err(|e| anyhow::anyhow!("resolve_id join: {e}"))?
}

fn parse_resolve_bound(out: &Bound<'_, PyAny>) -> HookResolveIdReturn {
    if out.is_none() {
        return Ok(None);
    }
    if let Ok(s) = out.cast::<PyString>() {
        let id = s.to_str()?.to_owned();
        return Ok(Some(HookResolveIdOutput::from_id(id)));
    }
    let dict = out
        .cast::<PyDict>()
        .map_err(|_| anyhow::anyhow!("resolve_id must return None, str, or dict with 'id'"))?;
    let id_item = get_mapping_item(dict, &["id"]).map_err(|e| anyhow::anyhow!("{}", e))?
        .ok_or_else(|| anyhow::anyhow!("resolve_id dict result must contain 'id'"))?;
    let id = extract_string(&id_item, "resolve_id id must be a string")
        .map_err(|e| anyhow::anyhow!("{}", e))?;
    Ok(Some(HookResolveIdOutput::from_id(id)))
}

pub(crate) fn parse_plugin_item(item: &Bound<'_, PyAny>) -> PyResult<Arc<PyPlugin>> {
    let mapping = item
        .cast::<PyDict>()
        .map_err(|_| PyTypeError::new_err("Each plugin must be a mapping"))?;
    super::parse::ensure_supported_mapping_fields(mapping, "Bundler.plugins[]", &["name", "resolve_id"])?;
    let name_item = get_mapping_item(mapping, &["name"])?
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("plugin.name is required"))?;
    let name = extract_string(&name_item, "plugin.name must be a string")?;
    let resolve_id = get_mapping_item(mapping, &["resolve_id"])?
        .map(|v| {
            if v.is_callable() {
                Ok(Arc::new(v.clone().unbind()))
            } else {
                Err(PyTypeError::new_err("plugin.resolve_id must be callable"))
            }
        })
        .transpose()?;
    Ok(Arc::new(PyPlugin::new(name, resolve_id)))
}
