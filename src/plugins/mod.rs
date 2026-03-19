mod app_entrypoint;
mod lightningcss;
mod runtime_module;
mod server_entrypoint;
mod shared;
mod vite;
mod vite_runtime;

pub(crate) use shared::{client_entry_import, server_entry_import};
pub(crate) use vite::VitePluginSpec;

#[cfg(not(test))]
use std::{collections::HashSet, path::Path};

#[cfg(not(test))]
use pyo3::{
    PyResult,
    exceptions::{PyTypeError, PyValueError},
    prelude::*,
    types::PyString,
};
#[cfg(not(test))]
use rolldown::plugin::__inner::SharedPluginable;

#[cfg(not(test))]
use crate::bundle::{NormalizedPage, VitePlugin, invalid_vite_plugin_message};

#[cfg(not(test))]
use self::shared::LIGHTNINGCSS_PLUGIN_ID;

#[cfg_attr(test, allow(dead_code))]
#[derive(Debug, Clone, Default)]
pub(crate) struct PluginSelection {
    pub(crate) bundler_plugin_ids: Option<Vec<String>>,
    pub(crate) vite_plugin_specs: Vec<VitePluginSpec>,
}

#[cfg(not(test))]
pub(crate) fn parse_plugin_selection(
    py: Python<'_>,
    plugins: Option<Vec<Py<PyAny>>>,
    cwd: &Path,
) -> PyResult<PluginSelection> {
    let Some(plugins) = plugins else {
        return Ok(PluginSelection::default());
    };

    let mut bundler_plugin_ids = Vec::new();
    let mut vite_plugin_specs = Vec::new();

    for plugin in plugins {
        let plugin = plugin.bind(py);
        if plugin.is_instance_of::<VitePlugin>() {
            let plugin = plugin.cast::<VitePlugin>()?;
            vite_plugin_specs.push(plugin.borrow().to_spec(py, cwd)?);
            continue;
        }

        let plugin_id = plugin
            .getattr("id")
            .map_err(|_| PyTypeError::new_err(invalid_vite_plugin_message()))?;
        let plugin_id = plugin_id
            .cast::<PyString>()
            .map_err(|_| PyTypeError::new_err(invalid_vite_plugin_message()))?
            .to_str()
            .map_err(|_| PyTypeError::new_err(invalid_vite_plugin_message()))?;
        if plugin_id.is_empty() {
            return Err(PyTypeError::new_err(invalid_vite_plugin_message()));
        }
        bundler_plugin_ids.push(plugin_id.to_owned());
    }

    Ok(PluginSelection {
        bundler_plugin_ids: if bundler_plugin_ids.is_empty() && !vite_plugin_specs.is_empty() {
            None
        } else {
            Some(bundler_plugin_ids)
        },
        vite_plugin_specs,
    })
}

#[cfg(not(test))]
pub(crate) struct ClientEntrypointPluginOptions<'a> {
    pub(crate) dev: bool,
    pub(crate) minify: bool,
    pub(crate) selection: &'a PluginSelection,
    pub(crate) include_app_entrypoint_plugin: bool,
}

#[cfg(not(test))]
fn resolve_bundler_plugin_ids(plugin_ids: Option<&[String]>) -> PyResult<Vec<&str>> {
    let mut resolved_ids = Vec::new();
    let mut seen_ids = HashSet::new();

    match plugin_ids {
        Some(plugin_ids) => {
            for plugin_id in plugin_ids {
                let plugin_id = plugin_id.as_str();
                if !seen_ids.insert(plugin_id.to_owned()) {
                    return Err(PyValueError::new_err(format!(
                        "duplicate bundler plugin id: {plugin_id}"
                    )));
                }
                match plugin_id {
                    LIGHTNINGCSS_PLUGIN_ID => resolved_ids.push(plugin_id),
                    _ => {
                        return Err(PyValueError::new_err(format!(
                            "unknown bundler plugin id: {plugin_id}"
                        )));
                    }
                }
            }
        }
        None => resolved_ids.push(LIGHTNINGCSS_PLUGIN_ID),
    }

    Ok(resolved_ids)
}

#[cfg(not(test))]
pub(crate) fn client_entrypoint_plugins(
    normalized: &[NormalizedPage],
    cwd: &Path,
    output_dir: &Path,
    options: ClientEntrypointPluginOptions<'_>,
) -> PyResult<Vec<SharedPluginable>> {
    let mut plugins: Vec<SharedPluginable> =
        resolve_bundler_plugin_ids(options.selection.bundler_plugin_ids.as_deref())?
            .into_iter()
            .map(|plugin_id| match plugin_id {
                LIGHTNINGCSS_PLUGIN_ID => {
                    lightningcss::client_plugin(normalized, cwd, output_dir, options.minify)
                }
                _ => unreachable!("validated plugin id"),
            })
            .collect();
    if options.include_app_entrypoint_plugin {
        plugins.push(app_entrypoint::plugin());
    }
    if !options.selection.vite_plugin_specs.is_empty() {
        plugins.push(vite::client_plugin(
            &options.selection.vite_plugin_specs,
            normalized,
            cwd,
            output_dir,
            options.dev,
        ));
    }
    Ok(plugins)
}

#[cfg(not(test))]
pub(crate) fn server_entrypoint_plugins(
    selection: &PluginSelection,
) -> PyResult<Vec<SharedPluginable>> {
    let mut plugins: Vec<SharedPluginable> =
        resolve_bundler_plugin_ids(selection.bundler_plugin_ids.as_deref())?
            .into_iter()
            .map(|plugin_id| match plugin_id {
                LIGHTNINGCSS_PLUGIN_ID => lightningcss::server_plugin(),
                _ => unreachable!("validated plugin id"),
            })
            .collect();
    plugins.push(runtime_module::plugin());
    plugins.push(server_entrypoint::plugin());
    Ok(plugins)
}
