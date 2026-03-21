mod lightningcss;
mod runtime_module;
mod server_entrypoint;
mod shared;
mod vite;
mod vite_runtime;
mod widget_entrypoint;

pub(crate) use shared::{client_entry_import, server_entry_import};
pub(crate) use vite::VitePluginSpec;

#[cfg(not(test))]
use std::path::Path;

#[cfg(not(test))]
use pyo3::{PyResult, prelude::*};
#[cfg(not(test))]
use rolldown::plugin::__inner::SharedPluginable;

#[cfg(not(test))]
use crate::bundle::{NormalizedPage, PluginInput};

#[cfg_attr(test, allow(dead_code))]
#[derive(Debug, Clone)]
pub(crate) struct PluginSelection {
    pub(crate) include_lightningcss: bool,
    pub(crate) vite_plugin_specs: Vec<VitePluginSpec>,
}

fn plugin_selection_with_vite_specs(vite_plugin_specs: Vec<VitePluginSpec>) -> PluginSelection {
    PluginSelection {
        vite_plugin_specs,
        ..PluginSelection::default()
    }
}

impl Default for PluginSelection {
    fn default() -> Self {
        Self {
            include_lightningcss: true,
            vite_plugin_specs: Vec::new(),
        }
    }
}

#[cfg(not(test))]
pub(crate) fn parse_plugin_selection(
    py: Python<'_>,
    plugins: Option<Vec<PluginInput>>,
    cwd: &Path,
) -> PyResult<PluginSelection> {
    let Some(plugins) = plugins else {
        return Ok(PluginSelection::default());
    };

    let mut vite_plugin_specs = Vec::new();

    for plugin in plugins {
        match plugin {
            PluginInput::LightningCSS => {}
            PluginInput::VitePlugin(plugin) => {
                vite_plugin_specs.push(plugin.bind(py).borrow().to_spec(py, cwd)?);
            }
        }
    }

    Ok(plugin_selection_with_vite_specs(vite_plugin_specs))
}

#[cfg(not(test))]
pub(crate) struct ClientEntrypointPluginOptions<'a> {
    pub(crate) dev: bool,
    pub(crate) minify: bool,
    pub(crate) selection: &'a PluginSelection,
    pub(crate) include_widget_entrypoint_plugin: bool,
}

#[cfg(not(test))]
pub(crate) fn client_entrypoint_plugins(
    normalized: &[NormalizedPage],
    cwd: &Path,
    output_dir: &Path,
    options: ClientEntrypointPluginOptions<'_>,
) -> PyResult<Vec<SharedPluginable>> {
    let mut plugins = Vec::new();
    if options.selection.include_lightningcss {
        plugins.push(lightningcss::client_plugin(
            normalized,
            cwd,
            output_dir,
            options.minify,
        ));
    }
    if options.include_widget_entrypoint_plugin {
        plugins.push(widget_entrypoint::plugin());
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
    let mut plugins = Vec::new();
    if selection.include_lightningcss {
        plugins.push(lightningcss::server_plugin());
    }
    plugins.push(runtime_module::plugin());
    plugins.push(server_entrypoint::plugin());
    Ok(plugins)
}

#[cfg(test)]
mod tests {
    use super::plugin_selection_with_vite_specs;

    #[test]
    fn empty_plugin_selection_keeps_lightningcss_enabled() {
        let selection = plugin_selection_with_vite_specs(vec![]);

        assert!(selection.include_lightningcss);
        assert!(selection.vite_plugin_specs.is_empty());
    }
}
