import { access } from "node:fs/promises";
import { dirname, join, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";
import { glob } from "tinyglobby";
import type { Plugin } from "vite";
import type { GdanskPluginOptions, ProjectPlugin, ResolvedGdanskOptions, WidgetDefinition } from "./types";

export function resolveOptions(
  options: GdanskPluginOptions = {},
  configRoot?: string,
): ResolvedGdanskOptions {
  const root = resolve(configRoot ?? options.root ?? process.cwd());
  const widgetsRoot = options.widgetsRoot ?? "widgets";
  const outDir = (options.outDir ?? ".gdansk").replace(/\/+$/, "");
  const host = options.host ?? "127.0.0.1";
  const ssrEndpoint = options.ssrEndpoint?.startsWith("/") ? options.ssrEndpoint : `/${options.ssrEndpoint ?? "__gdansk_ssr"}`;

  return {
    host,
    outDir,
    outDirPath: resolve(root, outDir),
    root,
    ssrEndpoint,
    ssrPort: options.ssrPort,
    vitePort: options.vitePort,
    widgetsRoot,
    widgetsRootPath: resolve(root, widgetsRoot),
  };
}

export async function discoverWidgets(options: ResolvedGdanskOptions): Promise<WidgetDefinition[]> {
  const entries = await glob("**/widget.{tsx,jsx}", {
    absolute: false,
    cwd: options.widgetsRootPath,
    onlyFiles: true,
  });

  return entries
    .sort()
    .map((entry) => {
      const widgetPath = toPosixPath(entry);
      const key = toPosixPath(dirname(widgetPath));

      return {
        clientCss: toPosixPath(join(options.outDir, key, "client.css")),
        clientEntry: toPosixPath(join(options.outDir, key, "client.js")),
        entry: resolve(options.widgetsRootPath, entry),
        key,
        serverEntry: toPosixPath(join(options.outDir, key, "server.js")),
        widgetPath,
      };
    });
}

export async function loadProjectPlugins(options: ResolvedGdanskOptions): Promise<Plugin[]> {
  const pluginsPath = resolve(options.root, "plugins");

  if (!(await pathExists(pluginsPath))) {
    return [];
  }

  const pluginFiles = await glob("*.mjs", {
    absolute: true,
    cwd: pluginsPath,
    onlyFiles: true,
  });

  const plugins: Plugin[] = [];

  for (const pluginFile of pluginFiles.sort()) {
    const module = (await import(pathToFileURL(pluginFile).href)) as { default?: ProjectPlugin };

    if (!module.default) {
      continue;
    }

    const entries = Array.isArray(module.default) ? module.default : [module.default];

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
