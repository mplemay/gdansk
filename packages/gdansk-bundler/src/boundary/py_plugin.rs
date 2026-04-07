use std::{borrow::Cow, sync::Arc};

use arcstr::ArcStr;
use pyo3::{exceptions::PyTypeError, prelude::*, types::{PyDict, PyString}};
use rolldown_common::{ModuleType, ResolvedExternal};
use rolldown_plugin::{
    HookLoadArgs, HookLoadOutput, HookLoadReturn, HookResolveIdArgs, HookResolveIdOutput,
    HookResolveIdReturn, HookTransformArgs, HookTransformOutput, HookTransformReturn, HookUsage,
    Plugin as RolldownPlugin, PluginContext, PluginHookMeta, PluginOrder, SharedLoadPluginContext,
    SharedTransformPluginContext,
};

use crate::plugin::Plugin;

use super::parse::{extract_string, get_mapping_item};

#[derive(Debug)]
pub(crate) struct PyPlugin {
    inner: Arc<PyPluginInner>,
}

#[derive(Debug)]
struct PyPluginInner {
    name: String,
    resolve_id: Option<Arc<Py<PyAny>>>,
    load: Option<Arc<Py<PyAny>>>,
    transform: Option<Arc<Py<PyAny>>>,
}

impl PyPlugin {
    pub(crate) fn new(
        name: String,
        resolve_id: Option<Arc<Py<PyAny>>>,
        load: Option<Arc<Py<PyAny>>>,
        transform: Option<Arc<Py<PyAny>>>,
    ) -> Self {
        Self {
            inner: Arc::new(PyPluginInner {
                name,
                resolve_id,
                load,
                transform,
            }),
        }
    }
}

impl RolldownPlugin for PyPlugin {
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

    fn resolve_id_meta(&self) -> Option<PluginHookMeta> {
        self.inner.resolve_id.is_some().then_some(PluginHookMeta {
            order: Some(PluginOrder::PinPost),
        })
    }

    fn load(
        &self,
        _ctx: SharedLoadPluginContext,
        args: &HookLoadArgs<'_>,
    ) -> impl std::future::Future<Output = HookLoadReturn> + Send {
        let inner = Arc::clone(&self.inner);
        let id = args.id.to_string();
        async move { load_python(&inner, id).await }
    }

    fn transform(
        &self,
        _ctx: SharedTransformPluginContext,
        args: &HookTransformArgs<'_>,
    ) -> impl std::future::Future<Output = HookTransformReturn> + Send {
        let inner = Arc::clone(&self.inner);
        let id = args.id.to_string();
        let code = args.code.clone();
        let module_type = args.module_type.to_string();
        async move { transform_python(&inner, code, id, module_type).await }
    }

    fn register_hook_usage(&self) -> HookUsage {
        let mut usage = HookUsage::empty();
        if self.inner.resolve_id.is_some() {
            usage |= HookUsage::ResolveId;
        }
        if self.inner.load.is_some() {
            usage |= HookUsage::Load;
        }
        if self.inner.transform.is_some() {
            usage |= HookUsage::Transform;
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

async fn load_python(inner: &PyPluginInner, id: String) -> HookLoadReturn {
    let Some(cb) = inner.load.as_ref().map(Arc::clone) else {
        return Ok(None);
    };
    tokio::task::spawn_blocking(move || {
        Python::attach(|py| {
            let bound = cb.bind(py);
            let out = bound
                .call1((id,))
                .map_err(|e| anyhow::anyhow!("{}", e))?;
            parse_load_bound(&out)
        })
    })
    .await
    .map_err(|e| anyhow::anyhow!("load join: {e}"))?
}

async fn transform_python(
    inner: &PyPluginInner,
    code: String,
    id: String,
    module_type: String,
) -> HookTransformReturn {
    let Some(cb) = inner.transform.as_ref().map(Arc::clone) else {
        return Ok(None);
    };
    tokio::task::spawn_blocking(move || {
        Python::attach(|py| {
            let bound = cb.bind(py);
            let out = bound
                .call1((code, id, module_type))
                .map_err(|e| anyhow::anyhow!("{}", e))?;
            parse_transform_bound(&out)
        })
    })
    .await
    .map_err(|e| anyhow::anyhow!("transform join: {e}"))?
}

fn parse_resolved_external(value: &Bound<'_, PyAny>) -> Result<ResolvedExternal, anyhow::Error> {
    if let Ok(b) = value.extract::<bool>() {
        return Ok(ResolvedExternal::Bool(b));
    }
    let s = extract_string(value, "resolve_id external must be bool or string")
        .map_err(|e| anyhow::anyhow!("{}", e))?;
    match s.as_str() {
        "absolute" => Ok(ResolvedExternal::Absolute),
        "relative" => Ok(ResolvedExternal::Relative),
        _ => Err(anyhow::anyhow!(
            "resolve_id external string must be 'absolute' or 'relative'"
        )),
    }
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
    let mut resolved = HookResolveIdOutput::from_id(id);
    if let Some(ext) = get_mapping_item(dict, &["external"]).map_err(|e| anyhow::anyhow!("{}", e))? {
        resolved.external = Some(parse_resolved_external(&ext)?);
    }
    if let Some(v) = get_mapping_item(dict, &["normalize_external_id"])
        .map_err(|e| anyhow::anyhow!("{}", e))?
    {
        resolved.normalize_external_id = Some(
            v.extract::<bool>()
                .map_err(|_| anyhow::anyhow!("normalize_external_id must be a boolean"))?,
        );
    }
    if let Some(v) = get_mapping_item(dict, &["package_json_path"])
        .map_err(|e| anyhow::anyhow!("{}", e))?
    {
        resolved.package_json_path = Some(
            extract_string(&v, "package_json_path must be a string").map_err(|e| anyhow::anyhow!("{}", e))?,
        );
    }
    Ok(Some(resolved))
}

fn parse_module_type_str(s: &str) -> ModuleType {
    ModuleType::from_str_with_fallback(s)
}

fn parse_load_bound(out: &Bound<'_, PyAny>) -> HookLoadReturn {
    if out.is_none() {
        return Ok(None);
    }
    let dict = out
        .cast::<PyDict>()
        .map_err(|_| anyhow::anyhow!("load must return None or a dict with 'code'"))?;
    let code_item = get_mapping_item(dict, &["code"]).map_err(|e| anyhow::anyhow!("{}", e))?
        .ok_or_else(|| anyhow::anyhow!("load dict result must contain 'code'"))?;
    let code = extract_string(&code_item, "load code must be a string")
        .map_err(|e| anyhow::anyhow!("{}", e))?;
    let mut output = HookLoadOutput {
        code: ArcStr::from(code),
        ..Default::default()
    };
    if let Some(mt) = get_mapping_item(dict, &["module_type", "moduleType"])
        .map_err(|e| anyhow::anyhow!("{}", e))?
    {
        let s = extract_string(&mt, "load module_type must be a string")
            .map_err(|e| anyhow::anyhow!("{}", e))?;
        output.module_type = Some(parse_module_type_str(&s));
    }
    Ok(Some(output))
}

fn parse_transform_bound(out: &Bound<'_, PyAny>) -> HookTransformReturn {
    if out.is_none() {
        return Ok(None);
    }
    let dict = out
        .cast::<PyDict>()
        .map_err(|_| anyhow::anyhow!("transform must return None or a dict"))?;
    let mut output = HookTransformOutput::default();
    if let Some(code_item) =
        get_mapping_item(dict, &["code"]).map_err(|e| anyhow::anyhow!("{}", e))?
    {
        output.code = Some(
            extract_string(&code_item, "transform code must be a string")
                .map_err(|e| anyhow::anyhow!("{}", e))?,
        );
    }
    if let Some(mt) = get_mapping_item(dict, &["module_type", "moduleType"])
        .map_err(|e| anyhow::anyhow!("{}", e))?
    {
        let s = extract_string(&mt, "transform module_type must be a string")
            .map_err(|e| anyhow::anyhow!("{}", e))?;
        output.module_type = Some(parse_module_type_str(&s));
    }
    if output.code.is_none() && output.map.is_none() && output.module_type.is_none() {
        return Ok(None);
    }
    Ok(Some(output))
}

fn optional_attr_callable(
    obj: &Bound<'_, PyAny>,
    keys: &[&str],
    label: &str,
) -> PyResult<Option<Arc<Py<PyAny>>>> {
    for key in keys {
        let v = match obj.getattr(*key) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if v.is_none() {
            continue;
        }
        if v.is_callable() {
            return Ok(Some(Arc::new(v.clone().unbind())));
        }
        return Err(PyTypeError::new_err(format!("{label} must be callable")));
    }
    Ok(None)
}

pub(crate) fn parse_plugin_item(item: &Bound<'_, PyAny>) -> PyResult<Arc<PyPlugin>> {
    if !item.is_instance_of::<Plugin>() {
        return Err(PyTypeError::new_err(
            "Each plugin must be an instance of Plugin (or a subclass)",
        ));
    }
    let name_item = item.getattr("name")?;
    let name = extract_string(&name_item, "plugin.name must be a string")?;
    if name.is_empty() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "plugin name must be non-empty",
        ));
    }
    let resolve_id = optional_attr_callable(
        item,
        &["resolve_id", "resolve"],
        "plugin.resolve_id / plugin.resolve",
    )?;
    let load = optional_attr_callable(item, &["load"], "plugin.load")?;
    let transform = optional_attr_callable(item, &["transform"], "plugin.transform")?;
    Ok(Arc::new(PyPlugin::new(name, resolve_id, load, transform)))
}
