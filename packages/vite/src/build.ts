import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { build, mergeConfig } from "vite";
import { pathExists } from "./context";
import type { GdanskManifest, LoadedProjectConfig, ResolvedGdanskOptions, WidgetDefinition } from "./types";

export async function buildWidgets(
  options: ResolvedGdanskOptions,
  widgets: WidgetDefinition[],
  config: LoadedProjectConfig = {},
): Promise<GdanskManifest> {
  await rm(options.outDirPath, { force: true, recursive: true });
  await mkdir(options.outDirPath, { recursive: true });

  for (const widget of widgets) {
    await buildClientWidget(options, widget, config);
    await buildServerWidget(options, widget, config);
  }

  const manifest: GdanskManifest = {
    outDir: options.outDir,
    root: options.root,
    widgets: Object.fromEntries(
      await Promise.all(
        widgets.map(async (widget) => [
          widget.key,
          {
            client: widget.clientEntry,
            css: (await pathExists(resolve(options.root, widget.clientCss))) ? widget.clientCss : null,
            entry: widget.widgetPath,
            server: widget.serverEntry,
          },
        ]),
      ),
    ),
  };

  await writeJson(resolve(options.outDirPath, "manifest.json"), manifest);
  await writeProductionServer(options);

  return manifest;
}

export async function readManifest(path: string): Promise<GdanskManifest> {
  return JSON.parse(await readFile(path, "utf8")) as GdanskManifest;
}

export async function writeRuntimeMetadata(path: string, metadata: unknown): Promise<void> {
  await writeJson(path, metadata);
}

async function buildClientWidget(
  options: ResolvedGdanskOptions,
  widget: WidgetDefinition,
  config: LoadedProjectConfig,
): Promise<void> {
  await build(
    mergeConfig(config, {
      appType: "custom",
      build: {
        copyPublicDir: false,
        cssCodeSplit: false,
        emptyOutDir: false,
        outDir: options.outDirPath,
        rollupOptions: {
          input: widget.clientSource,
          output: {
            assetFileNames: (assetInfo: { names?: string[]; originalFileNames?: string[] }) =>
              resolveClientAssetPath(options, widget, assetInfo),
            entryFileNames: toOutputPath(options, widget.clientEntry),
            inlineDynamicImports: true,
          },
        },
        sourcemap: true,
      },
      configFile: false,
      root: options.root,
    }),
  );
}

async function buildServerWidget(
  options: ResolvedGdanskOptions,
  widget: WidgetDefinition,
  config: LoadedProjectConfig,
): Promise<void> {
  await build(
    mergeConfig(config, {
      appType: "custom",
      build: {
        copyPublicDir: false,
        emptyOutDir: false,
        outDir: options.outDirPath,
        rollupOptions: {
          input: widget.entry,
          output: {
            entryFileNames: toOutputPath(options, widget.serverEntry),
            inlineDynamicImports: true,
          },
        },
        sourcemap: true,
        ssr: widget.entry,
      },
      configFile: false,
      root: options.root,
    }),
  );
}

function resolveClientAssetPath(
  options: ResolvedGdanskOptions,
  widget: WidgetDefinition,
  assetInfo: { names?: string[]; originalFileNames?: string[] },
): string {
  const fileName = assetInfo.names?.[0] ?? assetInfo.originalFileNames?.[0] ?? "";

  if (fileName.endsWith(".css")) {
    return toOutputPath(options, widget.clientCss);
  }

  return `${widget.key}/assets/[name]-[hash][extname]`;
}

async function writeJson(path: string, value: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, `${JSON.stringify(value, null, 2)}\n`);
}

function toOutputPath(options: ResolvedGdanskOptions, path: string): string {
  const prefix = `${options.outDir}/`;

  if (path.startsWith(prefix)) {
    return path.slice(prefix.length);
  }

  return path;
}

async function writeProductionServer(options: ResolvedGdanskOptions): Promise<void> {
  const path = resolve(options.outDirPath, "server.js");
  const runtimeModuleUrl = new URL("../runtime.js", import.meta.url).href;
  const runtimeOptions = {
    host: options.host,
    outDir: options.outDir,
    ssrEndpoint: options.ssrEndpoint,
    ssrPort: options.ssrPort,
    vitePort: options.vitePort,
    widgetsRoot: options.widgetsRoot,
  };

  await writeFile(
    path,
    [
      'import { dirname, resolve } from "node:path";',
      'import { fileURLToPath } from "node:url";',
      `import { createGdanskRuntime } from "${runtimeModuleUrl}";`,
      "",
      "const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');",
      `const runtime = await createGdanskRuntime({ ...${JSON.stringify(runtimeOptions)}, root });`,
      "await runtime.startProductionServer();",
      "await new Promise(() => {});",
      "",
    ].join("\n"),
  );
}
