import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

import { build, mergeConfig } from "vite";
import type { UserConfig } from "vite";

import type {
  GdanskManifest,
  GdanskPreparedProject,
  InlineWidgetBundle,
  LoadedProjectConfig,
  ResolvedGdanskOptions,
  WidgetDefinition,
} from "./types";
import { createGdanskVirtualModulesPlugin } from "./virtual";

export const GDANSK_MANIFEST_FILENAME = "gdansk-manifest.json";
const MAX_INLINE_ASSET_SIZE = Number.MAX_SAFE_INTEGER;
const TEXT_DECODER = new TextDecoder();

type AssetSource = string | Uint8Array;

type ViteMetadata = {
  importedAssets?: Set<string>;
  importedCss?: Set<string>;
};

type InlineBuildAsset = {
  fileName: string;
  source: AssetSource;
  type: "asset";
};

type InlineBuildChunk = {
  code: string;
  dynamicImports: string[];
  fileName: string;
  imports: string[];
  isEntry: boolean;
  type: "chunk";
  viteMetadata?: ViteMetadata;
};

type InlineBuildArtifact = InlineBuildAsset | InlineBuildChunk;

type InlineBuildOutput = {
  output: InlineBuildArtifact[];
};

type WidgetBuildFunction = (widget: WidgetDefinition, index: number) => Promise<InlineBuildOutput[]>;

export function createBuildConfig(options: ResolvedGdanskOptions, prepared: GdanskPreparedProject): UserConfig {
  return {
    appType: "custom",
    builder: {
      sharedPlugins: true,
      async buildApp(builder) {
        await writeInlineManifestFromWidgetBuilds(options, prepared.widgets, async (_widget, index) => {
          const envName = widgetEnvironmentName(index);
          const environment = builder.environments[envName];
          if (!environment) {
            throw new Error(`Gdansk build environment "${envName}" was not configured.`);
          }

          return normalizeBuildOutputs(await builder.build(environment));
        });
      },
    },
    build: {
      copyPublicDir: false,
      emptyOutDir: false,
      outDir: options.buildDirectory,
      sourcemap: false,
      write: false,
    },
    environments: Object.fromEntries(
      prepared.widgets.map((widget, index) => [
        widgetEnvironmentName(index),
        {
          build: createWidgetBuildOptions(options, widget),
        },
      ]),
    ),
  };
}

export async function buildWidgets(
  options: ResolvedGdanskOptions,
  prepared: GdanskPreparedProject,
  config: LoadedProjectConfig = {},
): Promise<GdanskManifest> {
  return writeInlineManifestFromWidgetBuilds(options, prepared.widgets, async (widget) => {
    const result = await build(
      mergeConfig(config, {
        appType: "custom",
        build: createWidgetBuildOptions(options, widget),
        configFile: false,
        plugins: [createGdanskVirtualModulesPlugin(options, prepared)],
        root: options.root,
      }),
    );

    return normalizeBuildOutputs(result);
  });
}

export async function readManifest(path: string): Promise<GdanskManifest> {
  return JSON.parse(await readFile(path, "utf8")) as GdanskManifest;
}

function widgetEnvironmentName(index: number): string {
  return `gdansk-widget-${index}`;
}

function createWidgetBuildOptions(
  options: ResolvedGdanskOptions,
  widget: WidgetDefinition,
): UserConfig["build"] {
  return {
    assetsInlineLimit: MAX_INLINE_ASSET_SIZE,
    copyPublicDir: false,
    cssCodeSplit: true,
    emptyOutDir: false,
    manifest: false,
    outDir: options.buildDirectory,
    rolldownOptions: {
      input: {
        [widget.key]: widget.clientModuleId,
      },
      output: {
        assetFileNames: `${widget.key}/assets/[name][extname]`,
        chunkFileNames: `${widget.key}/[name].js`,
        codeSplitting: false,
        entryFileNames: `${widget.key}/client.js`,
      },
    },
    sourcemap: false,
    write: false,
  };
}

async function writeInlineManifestFromWidgetBuilds(
  options: ResolvedGdanskOptions,
  widgets: WidgetDefinition[],
  buildWidget: WidgetBuildFunction,
): Promise<GdanskManifest> {
  await rm(options.buildDirectoryPath, { force: true, recursive: true });
  await mkdir(options.buildDirectoryPath, { recursive: true });

  const manifestWidgets: GdanskManifest["widgets"] = {};

  for (const [index, widget] of widgets.entries()) {
    manifestWidgets[widget.key] = {
      entry: widget.widgetPath,
      inline: extractInlineWidgetBundle(widget, await buildWidget(widget, index)),
    };
  }

  const manifest: GdanskManifest = {
    outDir: options.buildDirectory,
    root: options.root,
    widgets: manifestWidgets,
  };

  await writeJson(resolve(options.buildDirectoryPath, GDANSK_MANIFEST_FILENAME), manifest);

  return manifest;
}

function extractInlineWidgetBundle(widget: WidgetDefinition, outputs: InlineBuildOutput[]): InlineWidgetBundle {
  const artifacts = outputs.flatMap((output) => output.output);
  const chunks = artifacts.filter(isChunk);
  const entryChunks = chunks.filter((chunk) => chunk.isEntry);

  if (entryChunks.length !== 1) {
    throw new Error(`Gdansk expected exactly one entry chunk for widget "${widget.key}".`);
  }

  const [entry] = entryChunks;
  const extraChunks = chunks.filter((chunk) => chunk !== entry);

  if (extraChunks.length > 0) {
    throw new Error(
      `Gdansk widget "${widget.key}" emitted extra JavaScript chunks: ${extraChunks
        .map((chunk) => chunk.fileName)
        .join(", ")}`,
    );
  }

  if (entry.imports.length > 0) {
    throw new Error(
      `Gdansk widget "${widget.key}" emitted imports that cannot be served as one HTML resource: ${entry.imports.join(
        ", ",
      )}`,
    );
  }

  const assets = artifacts.filter(isAsset);
  const nonCssAssets = assets.filter((asset) => !isCssFile(asset.fileName));

  if (nonCssAssets.length > 0) {
    throw new Error(
      `Gdansk widget "${widget.key}" emitted non-CSS assets after inlining: ${nonCssAssets
        .map((asset) => asset.fileName)
        .join(", ")}`,
    );
  }

  return {
    script: entry.code,
    styles: collectInlineStyles(widget, entry, assets),
  };
}

function collectInlineStyles(
  widget: WidgetDefinition,
  entry: InlineBuildChunk,
  assets: InlineBuildAsset[],
): string[] {
  const assetsByFileName = new Map(assets.map((asset) => [asset.fileName, asset]));
  const cssFromMetadata = [...(entry.viteMetadata?.importedCss ?? [])];
  const cssFileNames =
    cssFromMetadata.length > 0
      ? cssFromMetadata
      : assets
          .filter((asset) => isCssFile(asset.fileName))
          .map((asset) => asset.fileName)
          .sort();

  return [...new Set(cssFileNames)].map((fileName) => {
    const asset = assetsByFileName.get(fileName);
    if (!asset) {
      throw new Error(`Gdansk widget "${widget.key}" referenced missing CSS asset "${fileName}".`);
    }

    return assetSourceToString(asset.source);
  });
}

function normalizeBuildOutputs(result: unknown): InlineBuildOutput[] {
  if (Array.isArray(result)) {
    return result.map(assertBuildOutput);
  }

  return [assertBuildOutput(result)];
}

function assertBuildOutput(value: unknown): InlineBuildOutput {
  if (!isBuildOutput(value)) {
    throw new Error("Gdansk inline production builds do not support watch-mode build outputs.");
  }

  return value;
}

function isBuildOutput(value: unknown): value is InlineBuildOutput {
  return typeof value === "object" && value !== null && Array.isArray((value as { output?: unknown }).output);
}

function isAsset(artifact: InlineBuildArtifact): artifact is InlineBuildAsset {
  return artifact.type === "asset";
}

function isChunk(artifact: InlineBuildArtifact): artifact is InlineBuildChunk {
  return artifact.type === "chunk";
}

function isCssFile(fileName: string): boolean {
  return fileName.endsWith(".css");
}

function assetSourceToString(source: AssetSource): string {
  if (typeof source === "string") {
    return source;
  }

  return TEXT_DECODER.decode(source);
}

async function writeJson(path: string, value: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, `${JSON.stringify(value)}\n`);
}
