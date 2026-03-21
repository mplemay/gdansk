#[cfg(not(test))]
use super::shared::SERVER_ENTRYPOINT_QUERY;
use super::shared::{GDANSK_RUNTIME_SPECIFIER, file_name_import_path};

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
struct GdanskServerEntrypointPlugin;

#[cfg(not(test))]
fn source_id(id: &str) -> Option<&str> {
    id.strip_suffix(SERVER_ENTRYPOINT_QUERY)
}

fn wrapper_source(source_id: &str) -> Option<String> {
    let import_path = file_name_import_path(source_id)?;
    Some(format!(
        r#"import {{ createElement }} from "react";
import {{ renderToString }} from "react-dom/server";
import {{ setSsrHtml }} from "{GDANSK_RUNTIME_SPECIFIER}";
import App from "{import_path}";

setSsrHtml(renderToString(createElement(App)));
"#
    ))
}

#[cfg(not(test))]
pub(super) fn plugin() -> SharedPluginable {
    Arc::new(GdanskServerEntrypointPlugin)
}

#[cfg(not(test))]
impl Plugin for GdanskServerEntrypointPlugin {
    fn name(&self) -> Cow<'static, str> {
        Cow::Borrowed("gdansk:server-entrypoint")
    }

    async fn resolve_id(
        &self,
        _ctx: &PluginContext,
        args: &HookResolveIdArgs<'_>,
    ) -> HookResolveIdReturn {
        if args.specifier.ends_with(SERVER_ENTRYPOINT_QUERY) {
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
    use super::{GDANSK_RUNTIME_SPECIFIER, wrapper_source};

    #[test]
    fn wrapper_source_imports_runtime_module() {
        let wrapper = wrapper_source("widgets/simple/widget.tsx").expect("expected server wrapper");
        assert!(wrapper.contains(&format!(
            r#"import {{ setSsrHtml }} from "{GDANSK_RUNTIME_SPECIFIER}";"#
        )));
    }

    #[test]
    fn wrapper_source_does_not_call_deno_ops_directly() {
        let wrapper = wrapper_source("widgets/simple/widget.tsx").expect("expected server wrapper");
        assert!(!wrapper.contains("Deno.core.ops.op_gdansk_set_html"));
    }

    #[test]
    fn wrapper_source_does_not_use_global_marker() {
        let wrapper = wrapper_source("widgets/simple/widget.tsx").expect("expected server wrapper");
        assert!(!wrapper.contains("globalThis.__gdansk_html"));
    }
}
