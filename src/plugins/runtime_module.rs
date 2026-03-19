#[cfg(not(test))]
use super::shared::{GDANSK_RUNTIME_MODULE_SOURCE, GDANSK_RUNTIME_SPECIFIER};

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
struct GdanskRuntimeModulePlugin;

#[cfg(not(test))]
pub(super) fn plugin() -> SharedPluginable {
    Arc::new(GdanskRuntimeModulePlugin)
}

#[cfg(not(test))]
impl Plugin for GdanskRuntimeModulePlugin {
    fn name(&self) -> std::borrow::Cow<'static, str> {
        Cow::Borrowed("gdansk:runtime-module")
    }

    async fn resolve_id(
        &self,
        _ctx: &PluginContext,
        args: &HookResolveIdArgs<'_>,
    ) -> HookResolveIdReturn {
        if args.specifier == GDANSK_RUNTIME_SPECIFIER {
            return Ok(Some(HookResolveIdOutput::from_id(GDANSK_RUNTIME_SPECIFIER)));
        }
        Ok(None)
    }

    async fn load(&self, _ctx: SharedLoadPluginContext, args: &HookLoadArgs<'_>) -> HookLoadReturn {
        if args.id != GDANSK_RUNTIME_SPECIFIER {
            return Ok(None);
        }
        Ok(Some(HookLoadOutput {
            code: GDANSK_RUNTIME_MODULE_SOURCE.into(),
            ..Default::default()
        }))
    }

    fn register_hook_usage(&self) -> HookUsage {
        HookUsage::ResolveId | HookUsage::Load
    }
}
