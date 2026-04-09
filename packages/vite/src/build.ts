import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { build } from "vite";
import type { Plugin } from "vite";
import { pathExists } from "./context";
import type { GdanskManifest, ResolvedGdanskOptions, WidgetDefinition } from "./types";

export async function buildWidgets(
  options: ResolvedGdanskOptions,
  widgets: WidgetDefinition[],
  plugins: Plugin[],
): Promise<GdanskManifest> {
  await rm(options.outDirPath, { force: true, recursive: true });
  await mkdir(options.outDirPath, { recursive: true });

  for (const widget of widgets) {
    await buildClientWidget(options, widget, plugins);
    await buildServerWidget(options, widget, plugins);
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
  plugins: Plugin[],
): Promise<void> {
  await build({
    appType: "custom",
    build: {
      cssCodeSplit: false,
      emptyOutDir: false,
      outDir: options.outDirPath,
      rollupOptions: {
        input: widget.entry,
        output: {
          assetFileNames: (assetInfo) => resolveClientAssetPath(options, widget, assetInfo),
          entryFileNames: toOutputPath(options, widget.clientEntry),
          inlineDynamicImports: true,
        },
      },
      sourcemap: true,
    },
    configFile: false,
    plugins: [react(), ...plugins],
    root: options.root,
  });
}

async function buildServerWidget(
  options: ResolvedGdanskOptions,
  widget: WidgetDefinition,
  plugins: Plugin[],
): Promise<void> {
  await build({
    appType: "custom",
    build: {
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
    plugins: [react(), ...plugins],
    root: options.root,
  });
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
