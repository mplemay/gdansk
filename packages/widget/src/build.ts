import { mkdir, rm } from "node:fs/promises";
import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { createBuilder, mergeConfig, type InlineConfig } from "vite";

import { collectTypedCssModuleStyles } from "./cssModuleStyles";
import { createGdanskCssModulesPlugin, createSharedCssModulesConfig } from "./cssModules";
import { renderDocument } from "./html";
import { discoverWidgets, loadWidgetDefinition, flattenWidgetPlugins, writeJson } from "./project";
import type { GdanskManifest, WidgetDefinition, WidgetSource } from "./types";
import { createBrowserDescriptorPlugin, createClientPlugin, GDANSK_CLIENT_PATH } from "./virtual";

export const GDANSK_MANIFEST_FILENAME = "gdansk-manifest.json";
const MAX_INLINE_ASSET_SIZE = Number.MAX_SAFE_INTEGER;
const TEXT_DECODER = new TextDecoder();

type BuildAsset = { fileName: string; source: string | Uint8Array; type: "asset" };
type BuildChunk = {
  code: string;
  dynamicImports: string[];
  fileName: string;
  imports: string[];
  isEntry: boolean;
  type: "chunk";
  viteMetadata?: { importedCss?: Set<string> };
};
type BuildArtifact = BuildAsset | BuildChunk;
type BuildOutput = { output: BuildArtifact[] };

export async function buildProject(root: string, outDirectory: string): Promise<GdanskManifest> {
  const outputPath = resolve(root, outDirectory);
  await rm(outputPath, { force: true, recursive: true });
  await mkdir(outputPath, { recursive: true });
  const widgets = await discoverWidgets(root);
  const manifest: GdanskManifest = { outDir: outDirectory, root, widgets: {} };

  for (const widget of widgets) {
    const definition = await loadWidgetDefinition(root, widget);
    const output = await buildWidget(root, widget, definition);
    const inline = await extractInlineBundle(widget, output);
    manifest.widgets[widget.key] = {
      entry: widget.widgetPath,
      html: renderDocument({ inlineScript: inline.script, metadata: definition.metadata, styles: inline.styles }),
    };
  }

  await writeJson(resolve(outputPath, GDANSK_MANIFEST_FILENAME), manifest);
  return manifest;
}

async function buildWidget(root: string, widget: WidgetSource, definition: WidgetDefinition): Promise<BuildOutput[]> {
  const userPlugins = await flattenWidgetPlugins(definition);
  const controlled: InlineConfig = {
    appType: "custom",
    builder: {},
    configFile: false,
    css: createSharedCssModulesConfig(),
    environments: {
      client: {
        build: {
          assetsInlineLimit: MAX_INLINE_ASSET_SIZE,
          copyPublicDir: false,
          cssCodeSplit: true,
          emitAssets: true,
          emptyOutDir: false,
          manifest: false,
          rolldownOptions: {
            input: { [widget.key]: GDANSK_CLIENT_PATH },
            output: {
              assetFileNames: `${widget.key}/assets/[name][extname]`,
              chunkFileNames: `${widget.key}/[name].js`,
              codeSplitting: false,
              entryFileNames: `${widget.key}/client.js`,
            },
          },
          sourcemap: false,
          write: false,
        },
        consumer: "client",
      },
    },
    logLevel: "warn",
    plugins: [
      createGdanskCssModulesPlugin(),
      createClientPlugin(widget),
      createBrowserDescriptorPlugin(),
      react(),
      ...userPlugins,
    ],
    resolve: {
      alias: [
        { find: /^@gdansk\/widget$/, replacement: "@gdansk/widget/client" },
        { find: "@", replacement: root },
      ],
    },
    root,
  };
  const builder = await createBuilder(mergeConfig(definition.vite, controlled));
  const environment = builder.environments.client;
  if (!environment) throw new Error(`Gdansk did not create a client environment for ${widget.key}.`);
  const result = await builder.build(environment);
  return normalizeOutputs(result);
}

async function extractInlineBundle(widget: WidgetSource, outputs: BuildOutput[]): Promise<{ script: string; styles: string[] }> {
  const artifacts = outputs.flatMap((output) => output.output);
  const chunks = artifacts.filter((artifact): artifact is BuildChunk => artifact.type === "chunk");
  const entries = chunks.filter((chunk) => chunk.isEntry);
  if (entries.length !== 1) throw new Error(`Gdansk expected one entry chunk for ${widget.key}.`);
  const [entry] = entries;
  if (!entry) throw new Error(`Gdansk expected one entry chunk for ${widget.key}.`);
  const extras = chunks.filter((chunk) => chunk !== entry);
  if (extras.length) throw new Error(`Gdansk widget ${widget.key} emitted extra chunks: ${extras.map((item) => item.fileName).join(", ")}`);
  const imports = [...entry.imports, ...entry.dynamicImports].filter((item) => item !== entry.fileName);
  if (imports.length) {
    throw new Error(
      `Gdansk widget ${widget.key} emitted imports and cannot be represented as one HTML resource: ${imports.join(", ")}`,
    );
  }
  const assets = artifacts.filter((artifact): artifact is BuildAsset => artifact.type === "asset");
  const nonCss = assets.filter((asset) => !asset.fileName.endsWith(".css"));
  if (nonCss.length) throw new Error(`Gdansk widget ${widget.key} emitted non-CSS assets: ${nonCss.map((item) => item.fileName).join(", ")}`);
  const byName = new Map(assets.map((asset) => [asset.fileName, asset]));
  const names = [...(entry.viteMetadata?.importedCss ?? [])];
  let styles = (names.length ? names : assets.map((asset) => asset.fileName).sort()).map((name) => {
    const asset = byName.get(name);
    if (!asset) throw new Error(`Gdansk widget ${widget.key} references missing CSS ${name}.`);
    return typeof asset.source === "string" ? asset.source : TEXT_DECODER.decode(asset.source);
  });
  if (!styles.length) styles = await collectTypedCssModuleStyles(widget.entry, entry.code);
  return { script: entry.code, styles };
}

function normalizeOutputs(value: unknown): BuildOutput[] {
  const outputs = Array.isArray(value) ? value : [value];
  return outputs.map((output) => {
    if (typeof output !== "object" || output === null || !("output" in output) || !Array.isArray(output.output)) {
      throw new Error("Gdansk does not support watch-mode production output.");
    }
    return output as BuildOutput;
  });
}
