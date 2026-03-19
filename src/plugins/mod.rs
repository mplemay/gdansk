mod app_entrypoint;
mod lightningcss;
mod runtime_module;
mod server_entrypoint;
mod shared;
mod vite;

pub(crate) use shared::{client_entry_import, server_entry_import};
pub(crate) use vite::VitePluginSpec;

#[cfg(not(test))]
use std::{collections::HashSet, path::Path};

use deno_core::serde_json::Value;
#[cfg(not(test))]
use pyo3::{PyResult, exceptions::PyValueError};
#[cfg(not(test))]
use rolldown::plugin::__inner::SharedPluginable;
use serde::Deserialize;

#[cfg(not(test))]
use crate::bundle::NormalizedPage;

#[cfg(not(test))]
use self::shared::LIGHTNINGCSS_PLUGIN_ID;

#[derive(Debug, Clone, Default)]
pub(crate) struct PluginSelection {
    pub(crate) bundler_plugin_ids: Option<Vec<String>>,
    pub(crate) vite_plugin_specs: Vec<VitePluginSpec>,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum PluginSpec {
    Bundler {
        id: String,
    },
    Vite {
        specifier: String,
        #[serde(default)]
        options: Value,
    },
}

fn parse_plugin_selection_payload(plugins_json: Option<&str>) -> Result<PluginSelection, String> {
    let Some(plugins_json) = plugins_json else {
        return Ok(PluginSelection::default());
    };

    let specs: Vec<PluginSpec> = deno_core::serde_json::from_str(plugins_json)
        .map_err(|err| format!("invalid plugin payload: {err}"))?;
    let mut bundler_plugin_ids = Vec::new();
    let mut vite_plugin_specs = Vec::new();

    for spec in specs {
        match spec {
            PluginSpec::Bundler { id } => bundler_plugin_ids.push(id),
            PluginSpec::Vite { specifier, options } => {
                vite_plugin_specs.push(VitePluginSpec { specifier, options });
            }
        }
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
pub(crate) fn parse_plugin_selection_json(plugins_json: Option<&str>) -> PyResult<PluginSelection> {
    parse_plugin_selection_payload(plugins_json).map_err(PyValueError::new_err)
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

#[cfg(test)]
mod tests {
    use super::parse_plugin_selection_payload;

    #[test]
    fn parse_plugin_selection_defaults_native_plugins_when_payload_is_missing() {
        let selection = parse_plugin_selection_payload(None).expect("payload should parse");

        assert!(selection.bundler_plugin_ids.is_none());
        assert!(selection.vite_plugin_specs.is_empty());
    }

    #[test]
    fn parse_plugin_selection_preserves_explicit_empty_native_plugin_list() {
        let selection = parse_plugin_selection_payload(Some("[]")).expect("payload should parse");

        assert_eq!(selection.bundler_plugin_ids, Some(Vec::new()));
        assert!(selection.vite_plugin_specs.is_empty());
    }

    #[test]
    fn parse_plugin_selection_keeps_native_defaults_for_vite_only_payloads() {
        let selection = parse_plugin_selection_payload(Some(
            r#"[{"kind":"vite","specifier":"file:///plugin.mjs","options":{"comment":"ok"}}]"#,
        ))
        .expect("payload should parse");

        assert!(selection.bundler_plugin_ids.is_none());
        assert_eq!(selection.vite_plugin_specs.len(), 1);
        assert_eq!(
            selection.vite_plugin_specs[0].specifier,
            "file:///plugin.mjs"
        );
        assert_eq!(selection.vite_plugin_specs[0].options["comment"], "ok");
    }

    #[test]
    fn parse_plugin_selection_splits_mixed_payloads() {
        let selection = parse_plugin_selection_payload(Some(
            r#"[{"kind":"bundler","id":"lightningcss"},{"kind":"vite","specifier":"file:///plugin.mjs","options":{}}]"#,
        ))
        .expect("payload should parse");

        assert_eq!(
            selection.bundler_plugin_ids,
            Some(vec!["lightningcss".to_owned()])
        );
        assert_eq!(selection.vite_plugin_specs.len(), 1);
        assert_eq!(
            selection.vite_plugin_specs[0].specifier,
            "file:///plugin.mjs"
        );
    }
}
