import { access, glob as globIterate, mkdir, writeFile } from "node:fs/promises";
import { dirname, join, relative, resolve, sep } from "node:path";

import { loadConfigFromFile, mergeConfig } from "vite";
import type { InlineConfig, Plugin, PluginOption } from "vite";

import type {
  GdanskPreparedProject,
  GdanskPluginOptions,
  LoadedProjectConfig,
  ResolvedGdanskOptions,
  WidgetDefinition,
} from "./types";

export function resolveOptions(options: GdanskPluginOptions = {}, configRoot?: string): ResolvedGdanskOptions {
  const root = resolve(configRoot ?? options.root ?? process.cwd());
  const widgetsRoot = options.widgetsRoot ?? "widgets";
  const outDir = options.assets ?? "assets";
  const generatedDir = "dist-src";
  const host = options.host ?? "127.0.0.1";
  const ssrEndpoint = "/ssr";

  return {
    generatedDir,
    generatedDirPath: resolve(root, generatedDir),
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
    const clientSource = toPosixPath(join(options.generatedDir, key, "client.tsx"));

    return {
      clientCss: toPosixPath(join(options.outDir, key, "client.css")),
      clientDevEntry: toPublicPath(clientSource),
      clientEntry: toPosixPath(join(options.outDir, key, "client.js")),
      clientSource: resolve(options.root, clientSource),
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
  await Promise.all(widgets.map((widget) => writeClientEntry(widget)));

  const ssrEntry = resolve(options.generatedDirPath, "__gdansk_ssr__.ts");
  await writeSSRRenderEntry(ssrEntry, widgets);

  return {
    ssrEntry,
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

function createImportPath(from: string, to: string): string {
  const relativePath = toPosixPath(relative(dirname(from), to));
  return relativePath.startsWith(".") ? relativePath : `./${relativePath}`;
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

function toPublicPath(path: string): string {
  return `/${path.replace(/^\/+/, "")}`;
}

async function writeClientEntry(widget: WidgetDefinition): Promise<void> {
  const sourceImport = createImportPath(widget.clientSource, widget.entry);

  await mkdir(dirname(widget.clientSource), { recursive: true });
  await writeFile(
    widget.clientSource,
    [
      'import React from "react";',
      'import { createRoot, hydrateRoot } from "react-dom/client";',
      `import App from "${sourceImport}";`,
      "",
      'const root = document.getElementById("root");',
      "",
      "if (!root) {",
      "  throw new Error('Gdansk expected a #root element for widget hydration.');",
      "}",
      "",
      "const element = (",
      "  <React.StrictMode>",
      "    <App />",
      "  </React.StrictMode>",
      ");",
      "",
      "if (root.hasChildNodes()) {",
      "  hydrateRoot(root, element);",
      "} else {",
      "  createRoot(root).render(element);",
      "}",
      "",
    ].join("\n"),
  );
}

async function writeSSRRenderEntry(path: string, widgets: WidgetDefinition[]): Promise<void> {
  const imports = widgets.map((widget, index) => {
    const specifier = createImportPath(path, widget.entry);
    return `import Widget${index} from "${specifier}";`;
  });

  const widgetEntries = widgets.map((widget, index) => `  ${JSON.stringify(widget.key)}: Widget${index},`);

  await mkdir(dirname(path), { recursive: true });
  await writeFile(
    path,
    [
      'import { createElement } from "react";',
      'import { renderToString } from "react-dom/server";',
      ...imports,
      "",
      "const widgets = {",
      ...widgetEntries,
      "} as const;",
      "",
      "export default async function renderWidget(widgetKey: string) {",
      "  const component = widgets[widgetKey as keyof typeof widgets];",
      "",
      "  if (!component) {",
      "    throw new Error(`Unknown widget: ${widgetKey}`);",
      "  }",
      "",
      "  return {",
      "    body: renderToString(createElement(component)),",
      "    head: [],",
      "  };",
      "}",
      "",
    ].join("\n"),
  );
}
