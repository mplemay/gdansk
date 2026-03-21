use std::path::Path;

pub(crate) const WIDGET_ENTRYPOINT_QUERY: &str = "?gdansk-widget-entry";
pub(crate) const SERVER_ENTRYPOINT_QUERY: &str = "?gdansk-server-entry";
pub(crate) const GDANSK_RUNTIME_SPECIFIER: &str = "gdansk:runtime";
pub(crate) const GDANSK_CSS_STUB_PREFIX: &str = "gdansk:css-stub:";
#[cfg(not(test))]
pub(crate) const LIGHTNINGCSS_PLUGIN_ID: &str = "lightningcss";
#[cfg(not(test))]
pub(crate) const GDANSK_RUNTIME_MODULE_SOURCE: &str = include_str!("../runtime.js");

pub(crate) fn client_entry_import(import: &str, is_widget: bool) -> String {
    if is_widget {
        format!("{import}{WIDGET_ENTRYPOINT_QUERY}")
    } else {
        import.to_owned()
    }
}

pub(crate) fn server_entry_import(import: &str) -> String {
    format!("{import}{SERVER_ENTRYPOINT_QUERY}")
}

pub(crate) fn file_name_import_path(source_id: &str) -> Option<String> {
    let file_name = Path::new(source_id).file_name()?.to_str()?;
    Some(format!("./{file_name}"))
}
