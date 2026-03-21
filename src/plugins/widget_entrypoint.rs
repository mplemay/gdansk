#[cfg(not(test))]
use super::shared::WIDGET_ENTRYPOINT_QUERY;
use super::shared::file_name_import_path;

#[cfg(not(test))]
use std::{borrow::Cow, sync::Arc};

#[cfg(not(test))]
use rolldown::plugin::{
    __inner::SharedPluginable, HookLoadArgs, HookLoadOutput, HookLoadReturn, HookResolveIdArgs,
    HookResolveIdOutput, HookResolveIdReturn, HookUsage, Plugin, PluginContext,
    SharedLoadPluginContext,
};

#[cfg(not(test))]
#[derive(Debug, Default)]
struct GdanskWidgetEntrypointPlugin;

#[cfg(not(test))]
fn source_id(id: &str) -> Option<&str> {
    id.strip_suffix(WIDGET_ENTRYPOINT_QUERY)
}

fn wrapper_source(source_id: &str) -> Option<String> {
    let import_path = file_name_import_path(source_id)?;
    Some(format!(
        r#"import {{ StrictMode, createElement }} from "react";
import {{ createRoot, hydrateRoot }} from "react-dom/client";
import App from "{import_path}";

const root = document.getElementById("root");
if (!root) throw new Error("Expected #root element");
const element = createElement(StrictMode, null, createElement(App));
if (root.hasChildNodes()) {{
  hydrateRoot(root, element);
}} else {{
  createRoot(root).render(element);
}}
"#
    ))
}

#[cfg(not(test))]
pub(super) fn plugin() -> SharedPluginable {
    Arc::new(GdanskWidgetEntrypointPlugin)
}

#[cfg(not(test))]
impl Plugin for GdanskWidgetEntrypointPlugin {
    fn name(&self) -> Cow<'static, str> {
        Cow::Borrowed("gdansk:widget-entrypoint")
    }

    async fn resolve_id(
        &self,
        _ctx: &PluginContext,
        args: &HookResolveIdArgs<'_>,
    ) -> HookResolveIdReturn {
        if args.specifier.ends_with(WIDGET_ENTRYPOINT_QUERY) {
            return Ok(Some(HookResolveIdOutput::from_id(args.specifier)));
        }
        Ok(None)
    }

    async fn load(&self, _ctx: SharedLoadPluginContext, args: &HookLoadArgs<'_>) -> HookLoadReturn {
        let Some(source_id) = source_id(args.id) else {
            return Ok(None);
        };
        let Some(wrapper_source) = wrapper_source(source_id) else {
            return Ok(None);
        };
        Ok(Some(HookLoadOutput {
            code: wrapper_source.into(),
            ..Default::default()
        }))
    }

    fn register_hook_usage(&self) -> HookUsage {
        HookUsage::ResolveId | HookUsage::Load
    }
}

#[cfg(test)]
mod tests {
    use super::wrapper_source;

    #[test]
    fn wrapper_source_bootstraps_client_widget() {
        let wrapper = wrapper_source("widgets/simple/widget.tsx").expect("expected widget wrapper");

        assert!(wrapper.contains(r#"import App from "./widget.tsx";"#));
        assert!(wrapper.contains("hydrateRoot"));
        assert!(wrapper.contains("createRoot"));
    }
}
