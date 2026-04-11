import { access, glob as globIterate } from "node:fs/promises";
import { dirname, join, resolve, sep } from "node:path";

import { loadConfigFromFile, mergeConfig } from "vite";
import type { InlineConfig, Plugin, PluginOption } from "vite";

import type {
  GdanskPreparedProject,
  GdanskPluginOptions,
  LoadedProjectConfig,
  ResolvedGdanskOptions,
  WidgetDefinition,
} from "./types";
import { createClientDevEntry, createClientModuleId, GDANSK_SSR_ENTRY_ID } from "./virtual";

export function resolveOptions(options: GdanskPluginOptions = {}, configRoot?: string): ResolvedGdanskOptions {
  const root = resolve(configRoot ?? options.root ?? process.cwd());
  const widgetsRoot = options.widgetsRoot ?? "widgets";
  const outDir = options.assets ?? "assets";
  const host = options.host ?? "127.0.0.1";
  const ssrEndpoint = "/ssr";

  return {
    host,
    outDir,
    outDirPath: resolve(root, outDir),
    root,
    ssrEndpoint,
    port: options.port ?? 13714,
    widgetsRoot,
    widgetsRootPath: resolve(root, widgetsRoot),
  };
}

async function globPaths(pattern: string, options: { absolute?: boolean; cwd: string }): Promise<string[]> {
  const { cwd, absolute = false } = options;
  const matches: string[] = [];
  for await (const entry of globIterate(pattern, { cwd })) {
    matches.push(absolute ? resolve(cwd, entry) : entry);
  }
  return matches;
}

export async function discoverWidgets(options: ResolvedGdanskOptions): Promise<WidgetDefinition[]> {
  const entries = await globPaths("**/widget.{tsx,jsx}", {
    cwd: options.widgetsRootPath,
  });

  return entries.sort().map((entry) => {
    const widgetPath = toPosixPath(entry);
    const key = toPosixPath(dirname(widgetPath));

    return {
      clientCss: toPosixPath(join(options.outDir, key, "client.css")),
      clientDevEntry: createClientDevEntry(key),
      clientEntry: toPosixPath(join(options.outDir, key, "client.js")),
      clientModuleId: createClientModuleId(key),
      entry: resolve(options.widgetsRootPath, entry),
      key,
      widgetPath,
    };
  });
}

export async function loadUserViteConfig(
  options: ResolvedGdanskOptions,
  command: "build" | "serve",
): Promise<LoadedProjectConfig> {
  const loaded = await loadConfigFromFile(
    {
      command,
      mode: command === "build" ? "production" : "development",
    },
    undefined,
    options.root,
  );
  const loadedConfig = loaded?.config ?? ({} satisfies InlineConfig);
  const { plugins: _, ...configWithoutPlugins } = loadedConfig;

  const plugins = (await normalizePlugins(loadedConfig.plugins)).filter((plugin) => plugin.name !== "@gdansk/vite");

  return mergeConfig(configWithoutPlugins, {
    plugins,
    root: options.root,
  } satisfies InlineConfig);
}

export async function prepareProject(options: ResolvedGdanskOptions): Promise<GdanskPreparedProject> {
  const widgets = await discoverWidgets(options);

  return {
    ssrEntryId: GDANSK_SSR_ENTRY_ID,
    widgets,
  };
}

export async function pathExists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

export function toPosixPath(path: string): string {
  return path.split(sep).join("/");
}

async function normalizePlugins(plugins: PluginOption | PluginOption[] | undefined): Promise<Plugin[]> {
  if (!plugins) {
    return [];
  }

  const entries = Array.isArray(plugins) ? plugins : [plugins];
  const normalized: Plugin[] = [];

  for (const entry of entries) {
    const plugin = await entry;

    if (!plugin) {
      continue;
    }

    if (Array.isArray(plugin)) {
      normalized.push(...(await normalizePlugins(plugin)));
      continue;
    }

    normalized.push(plugin);
  }

  return normalized;
}
