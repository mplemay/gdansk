#![cfg_attr(test, allow(dead_code, unused_imports))]

use std::{
    path::{Path, PathBuf},
    sync::Arc,
};

use deno_core::serde_json::Value;
#[cfg(not(test))]
use rolldown::plugin::__inner::SharedPluginable;
use rolldown_common::Output;
#[cfg(not(test))]
use rolldown_common::{OutputAsset, StrOrBytes};
#[cfg(not(test))]
use rolldown_plugin::{HookUsage, Plugin, PluginContext, SharedTransformPluginContext};
use serde::{Deserialize, Serialize};
#[cfg(not(test))]
use std::{borrow::Cow, collections::HashMap};

use crate::bundle::NormalizedPage;

use super::vite_runtime::{PluginAssetInput, run_embedded_vite_plugins};

const VITE_BRIDGE_PLUGIN_ID: &str = "gdansk-vite-bridge";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) struct VitePluginSpec {
    pub(crate) specifier: String,
    #[serde(default)]
    pub(crate) options: Value,
}

#[derive(Debug)]
struct VitePluginBridge {
    specs: Arc<[VitePluginSpec]>,
    entry_modules: Arc<[String]>,
    pages: PathBuf,
    output_root: PathBuf,
    dev: bool,
}

impl VitePluginBridge {
    fn new(
        specs: Vec<VitePluginSpec>,
        entry_modules: Vec<String>,
        pages: PathBuf,
        output_root: PathBuf,
        dev: bool,
    ) -> Self {
        Self {
            specs: specs.into(),
            entry_modules: entry_modules.into(),
            pages,
            output_root,
            dev,
        }
    }

    fn collect_css_assets(
        &self,
        bundle: &[Output],
    ) -> Result<Vec<PluginAssetInput>, std::io::Error> {
        let mut assets = Vec::new();
        for output in bundle {
            let Output::Asset(asset) = output else {
                continue;
            };
            if !asset.filename.ends_with(".css") {
                continue;
            }

            let asset_path = self.output_root.join(asset.filename.as_str());
            assets.push(PluginAssetInput {
                filename: asset.filename.to_string(),
                path: asset_path.to_string_lossy().into_owned(),
                code: asset
                    .source
                    .clone()
                    .try_into_string()
                    .map_err(std::io::Error::other)?,
            });
        }
        Ok(assets)
    }

    fn normalize_watch_file(&self, watch_file: &str) -> String {
        let watch_path = Path::new(watch_file);
        let absolute = if watch_path.is_absolute() {
            watch_path.to_path_buf()
        } else {
            self.pages.join(watch_path)
        };
        let normalized = absolute
            .canonicalize()
            .unwrap_or_else(|_| dunce::simplified(&absolute).to_path_buf());
        normalized.to_string_lossy().into_owned()
    }

    fn css_probe_assets(&self, id: &str, code: &str) -> Vec<PluginAssetInput> {
        let filename = Path::new(id)
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("style.css")
            .to_owned();
        vec![PluginAssetInput {
            filename,
            path: id.to_owned(),
            code: code.to_owned(),
        }]
    }

    fn is_entry_module(&self, id: &str) -> bool {
        let normalized_id = id.replace('\\', "/");
        self.entry_modules.iter().any(|entry| {
            normalized_id == *entry
                || normalized_id.ends_with(entry.as_str())
                || normalized_id.ends_with(&format!("/{entry}"))
        })
    }
}

#[cfg(not(test))]
pub(crate) fn client_plugin(
    specs: &[VitePluginSpec],
    normalized: &[NormalizedPage],
    pages: &Path,
    output_dir: &Path,
    dev: bool,
) -> SharedPluginable {
    let output_root = if output_dir.is_absolute() {
        output_dir.to_path_buf()
    } else {
        pages.join(output_dir)
    };
    let entry_modules = normalized.iter().map(|page| page.import.clone()).collect();
    Arc::new(VitePluginBridge::new(
        specs.to_vec(),
        entry_modules,
        pages.to_path_buf(),
        output_root,
        dev,
    ))
}

#[cfg(not(test))]
impl Plugin for VitePluginBridge {
    fn name(&self) -> Cow<'static, str> {
        Cow::Borrowed(VITE_BRIDGE_PLUGIN_ID)
    }

    async fn transform(
        &self,
        ctx: SharedTransformPluginContext,
        args: &rolldown_plugin::HookTransformArgs<'_>,
    ) -> rolldown_plugin::HookTransformReturn {
        if !self.dev || args.id.starts_with('\0') || !self.is_entry_module(args.id) {
            return Ok(None);
        }

        let probe_path = self
            .output_root
            .join("__gdansk_watch_probe__.css")
            .to_string_lossy()
            .into_owned();
        let specs = self.specs.clone();
        let assets = self.css_probe_assets(&probe_path, "");
        let pages = self.pages.clone();
        let result =
            tokio::task::spawn_blocking(move || run_embedded_vite_plugins(&specs, &pages, assets))
                .await
                .map_err(std::io::Error::other)?
                .map_err(std::io::Error::other)?;

        for watch_file in result.watch_files {
            ctx.add_watch_file(&self.normalize_watch_file(&watch_file));
        }

        Ok(None)
    }

    async fn generate_bundle(
        &self,
        ctx: &PluginContext,
        args: &mut rolldown_plugin::HookGenerateBundleArgs<'_>,
    ) -> rolldown_plugin::HookNoopReturn {
        let css_assets = self.collect_css_assets(args.bundle)?;
        if css_assets.is_empty() {
            return Ok(());
        }

        let specs = self.specs.clone();
        let pages = self.pages.clone();
        let result = tokio::task::spawn_blocking(move || {
            run_embedded_vite_plugins(&specs, &pages, css_assets)
        })
        .await
        .map_err(std::io::Error::other)?
        .map_err(std::io::Error::other)?;

        for watch_file in result.watch_files {
            ctx.add_watch_file(&self.normalize_watch_file(&watch_file));
        }

        let changed_assets: HashMap<_, _> = result
            .assets
            .into_iter()
            .map(|asset| (asset.filename, asset.code))
            .collect();
        if changed_assets.is_empty() {
            return Ok(());
        }

        for output in args.bundle.iter_mut() {
            let Output::Asset(asset) = output else {
                continue;
            };
            let Some(code) = changed_assets.get(asset.filename.as_str()) else {
                continue;
            };
            *output = Output::Asset(Arc::new(OutputAsset {
                names: asset.names.clone(),
                original_file_names: asset.original_file_names.clone(),
                filename: asset.filename.clone(),
                source: StrOrBytes::from(code.clone()),
            }));
        }

        Ok(())
    }

    fn register_hook_usage(&self) -> HookUsage {
        let mut usage = HookUsage::GenerateBundle;
        if self.dev {
            usage |= HookUsage::Transform;
        }
        usage
    }
}
