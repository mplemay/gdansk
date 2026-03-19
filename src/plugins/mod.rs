mod app_entrypoint;
mod lightningcss;
mod runtime_module;
mod server_entrypoint;
mod shared;

pub(crate) use shared::{client_entry_import, server_entry_import};

#[cfg(not(test))]
use std::{collections::HashSet, path::Path};

#[cfg(not(test))]
use pyo3::{PyResult, exceptions::PyValueError};
#[cfg(not(test))]
use rolldown::plugin::__inner::SharedPluginable;

#[cfg(not(test))]
use crate::bundle::NormalizedPage;

#[cfg(not(test))]
use self::shared::LIGHTNINGCSS_PLUGIN_ID;

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
    minify: bool,
    plugin_ids: Option<&[String]>,
    include_app_entrypoint_plugin: bool,
) -> PyResult<Vec<SharedPluginable>> {
    let mut plugins: Vec<SharedPluginable> = resolve_bundler_plugin_ids(plugin_ids)?
        .into_iter()
        .map(|plugin_id| match plugin_id {
            LIGHTNINGCSS_PLUGIN_ID => {
                lightningcss::client_plugin(normalized, cwd, output_dir, minify)
            }
            _ => unreachable!("validated plugin id"),
        })
        .collect();
    if include_app_entrypoint_plugin {
        plugins.push(app_entrypoint::plugin());
    }
    Ok(plugins)
}

#[cfg(not(test))]
pub(crate) fn server_entrypoint_plugins(
    plugin_ids: Option<&[String]>,
) -> PyResult<Vec<SharedPluginable>> {
    let mut plugins: Vec<SharedPluginable> = resolve_bundler_plugin_ids(plugin_ids)?
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
