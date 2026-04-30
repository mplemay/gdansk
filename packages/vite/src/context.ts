import { access, glob as globIterate } from "node:fs/promises";
import { dirname, join, resolve, sep } from "node:path";

import type { Alias, InlineConfig, Plugin, PluginOption } from "vite";

import type {
  AppModuleDefinition,
  GdanskPreparedPageProject,
  GdanskPreparedProject,
  GdanskPagePluginOptions,
  GdanskPluginOptions,
  LoadedProjectConfig,
  ResolvedGdanskPageOptions,
  ResolvedGdanskOptions,
  WidgetDefinition,
} from "./types";
import { createClientDevEntry, createClientModuleId } from "./virtual";
import { loadViteModule } from "./vite-runtime";

export function resolveOptions(options: GdanskPluginOptions = {}, configRoot?: string): ResolvedGdanskOptions {
  const root = resolve(configRoot ?? options.root ?? process.cwd());
  const widgetsDirectory = "widgets";
  const buildDirectory = options.buildDirectory ?? "dist";
  const host = options.host ?? "127.0.0.1";

  return {
    buildDirectory,
    buildDirectoryPath: resolve(root, buildDirectory),
    host,
    root,
    port: options.port ?? 13714,
    widgetsDirectory,
    widgetsDirectoryPath: resolve(root, widgetsDirectory),
  };
}

export function resolvePageOptions(
  options: GdanskPagePluginOptions = {},
  configRoot?: string,
): ResolvedGdanskPageOptions {
  return resolveOptions(options, configRoot);
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
    cwd: options.widgetsDirectoryPath,
  });

  return entries.sort().map((entry) => {
    const widgetPath = toPosixPath(entry);
    const key = toPosixPath(dirname(widgetPath));

    return {
      clientCss: toPosixPath(join(options.buildDirectory, key, "client.css")),
      clientDevEntry: createClientDevEntry(key),
      clientEntry: toPosixPath(join(options.buildDirectory, key, "client.js")),
      clientModuleId: createClientModuleId(key),
      entry: resolve(options.widgetsDirectoryPath, entry),
      key,
      widgetPath,
    };
  });
}

export async function loadUserViteConfig(
  options: ResolvedGdanskOptions,
  command: "build" | "serve",
): Promise<LoadedProjectConfig> {
  const { loadConfigFromFile, mergeConfig } = await loadViteModule();
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
    resolve: {
      ...(loadedConfig.resolve ?? {}),
      alias: mergeDefaultAlias(loadedConfig.resolve?.alias, options.root),
    },
  } satisfies InlineConfig);
}

export async function prepareProject(options: ResolvedGdanskOptions): Promise<GdanskPreparedProject> {
  const widgets = await discoverWidgets(options);

  return {
    widgets,
  };
}

export async function preparePageProject(options: ResolvedGdanskPageOptions): Promise<GdanskPreparedPageProject> {
  const appRoot = resolve(options.root, "app");
  const [pages, layouts] = await Promise.all([
    discoverAppModules(appRoot, "page"),
    discoverAppModules(appRoot, "layout"),
  ]);

  if (pages.length === 0) {
    throw new Error("The frontend app must contain at least one app/**/page.tsx or app/**/page.jsx file");
  }

  return {
    layouts,
    pages,
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

async function discoverAppModules(appRoot: string, name: "layout" | "page"): Promise<AppModuleDefinition[]> {
  if (!(await pathExists(appRoot))) {
    return [];
  }

  const entries = await globPaths(`**/${name}.{tsx,jsx}`, {
    cwd: appRoot,
  });
  const modules = entries.map((entry) => {
    const directory = toPosixPath(dirname(entry));
    return {
      entry: resolve(appRoot, entry),
      key: directory === "." ? "/" : directory,
    };
  });

  return ensureUniqueAppModules(modules, name);
}

function ensureUniqueAppModules(modules: AppModuleDefinition[], kind: "layout" | "page"): AppModuleDefinition[] {
  const seen = new Map<string, string>();

  for (const module of modules) {
    const existing = seen.get(module.key);

    if (existing) {
      throw new Error(
        `The frontend app contains multiple app/**/${kind} files for "${module.key}": ${existing} and ${module.entry}`,
      );
    }

    seen.set(module.key, module.entry);
  }

  return modules.sort((left, right) => left.key.localeCompare(right.key) || left.entry.localeCompare(right.entry));
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

type AliasOption = NonNullable<NonNullable<InlineConfig["resolve"]>["alias"]>;

function mergeDefaultAlias(alias: AliasOption | undefined, root: string): AliasOption {
  if (Array.isArray(alias)) {
    return hasNamedAlias(alias, "@") ? alias : [...alias, { find: "@", replacement: root }];
  }

  if (typeof alias === "object" && alias !== null && "@" in alias) {
    return alias;
  }

  return {
    ...(alias ?? {}),
    "@": root,
  };
}

function hasNamedAlias(aliases: Alias[], name: string): boolean {
  return aliases.some((alias) => alias.find === name);
}
