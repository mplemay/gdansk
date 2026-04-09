import { access, glob as globIterate, mkdir, writeFile } from "node:fs/promises";
import { dirname, join, relative, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";
import { loadConfigFromFile, mergeConfig } from "vite";
import type { InlineConfig, Plugin, PluginOption } from "vite";
import type {
  GdanskPluginOptions,
  LoadedProjectConfig,
  ProjectPlugin,
  ResolvedGdanskOptions,
  WidgetDefinition,
} from "./types";

export function resolveOptions(
  options: GdanskPluginOptions = {},
  configRoot?: string,
): ResolvedGdanskOptions {
  const root = resolve(configRoot ?? options.root ?? process.cwd());
  const widgetsRoot = options.widgetsRoot ?? "widgets";
  const outDir = (options.outDir ?? ".gdansk").replace(/\/+$/, "");
  const generatedDir = `${outDir}-src`;
  const host = process.env.GDANSK_HOST?.trim() || options.host || "127.0.0.1";
  const ssrEndpoint = options.ssrEndpoint?.startsWith("/") ? options.ssrEndpoint : `/${options.ssrEndpoint ?? "__gdansk_ssr"}`;

  return {
    generatedDir,
    generatedDirPath: resolve(root, generatedDir),
    host,
    outDir,
    outDirPath: resolve(root, outDir),
    root,
    ssrEndpoint,
    ssrPort: readPort(process.env.GDANSK_SSR_PORT) ?? options.ssrPort,
    vitePort: options.vitePort,
    widgetsRoot,
    widgetsRootPath: resolve(root, widgetsRoot),
  };
}

async function globPaths(
  pattern: string,
  options: { absolute?: boolean; cwd: string },
): Promise<string[]> {
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

  return entries
    .sort()
    .map((entry) => {
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
        serverEntry: toPosixPath(join(options.outDir, key, "server.js")),
        widgetPath,
      };
    });
}

export async function ensureNoopEntry(options: ResolvedGdanskOptions): Promise<string> {
  const path = resolve(options.generatedDirPath, "__noop__.ts");
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, "export default null;\n");
  return path;
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

  const plugins = [
    ...(await normalizePlugins(loadedConfig.plugins)).filter((plugin) => plugin.name !== "@gdansk/vite"),
    ...(await loadProjectPlugins(options)),
  ];

  return mergeConfig(
    configWithoutPlugins,
    {
      plugins,
      root: options.root,
    } satisfies InlineConfig,
  );
}

export async function prepareWidgets(options: ResolvedGdanskOptions): Promise<WidgetDefinition[]> {
  const widgets = await discoverWidgets(options);
  await Promise.all(widgets.map((widget) => writeClientEntry(widget)));
  return widgets;
}

export async function loadProjectPlugins(options: ResolvedGdanskOptions): Promise<Plugin[]> {
  const pluginsPath = resolve(options.root, "plugins");

  if (!(await pathExists(pluginsPath))) {
    return [];
  }

  const pluginFiles = await globPaths("*.mjs", {
    absolute: true,
    cwd: pluginsPath,
  });

  const plugins: Plugin[] = [];

  for (const pluginFile of pluginFiles.sort()) {
    const module = (await import(pathToFileURL(pluginFile).href)) as { default?: ProjectPlugin };

    if (!module.default) {
      continue;
    }

    const entries = (Array.isArray(module.default) ? module.default : [module.default]) as Plugin[];

    for (const entry of entries) {
      plugins.push(entry);
    }
  }

  return plugins;
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

function readPort(value: string | undefined): number | undefined {
  if (!value) {
    return undefined;
  }

  const normalized = value.trim();
  if (normalized === "") {
    return undefined;
  }

  const port = Number(normalized);
  if (!Number.isInteger(port) || port <= 0 || port > 65535) {
    return undefined;
  }

  return port;
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
      '  throw new Error(\'Gdansk expected a #root element for widget hydration.\');',
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
