import { glob as globIterate, mkdir, writeFile } from "node:fs/promises";
import { dirname, relative, resolve, sep } from "node:path";

import react from "@vitejs/plugin-react";
import { runnerImport, type Plugin, type PluginOption } from "vite";

import { assertWidgetDefinition } from "./definition";
import type { GdanskDevelopmentManifest, GdanskManifest, WidgetDefinition, WidgetSource } from "./types";
import { createDescriptorCssPlugin } from "./virtual";

export function toPosixPath(path: string): string {
  return path.split(sep).join("/");
}

export async function discoverWidgets(root: string): Promise<WidgetSource[]> {
  const widgetsRoot = resolve(root, "widgets");
  const entries: string[] = [];
  for await (const entry of globIterate("**/widget.{tsx,jsx}", { cwd: widgetsRoot })) entries.push(entry);
  return entries.sort().map((entry) => {
    const widgetPath = toPosixPath(entry);
    return {
      entry: resolve(widgetsRoot, entry),
      key: toPosixPath(dirname(widgetPath)),
      widgetPath,
    };
  });
}

export async function loadWidgetDefinition(root: string, widget: WidgetSource): Promise<WidgetDefinition> {
  const loaded = await runnerImport<{ default?: unknown }>(widget.entry, {
    configFile: false,
    plugins: [createDescriptorCssPlugin(), react()],
    resolve: { alias: { "@": root } },
    root,
  });
  if (typeof loaded.module.default !== "function") {
    throw new Error(`${widget.widgetPath} must default-export a function.`);
  }
  return assertWidgetDefinition(loaded.module.default(), widget.widgetPath);
}

export async function flattenWidgetPlugins(definition: WidgetDefinition): Promise<Plugin[]> {
  const plugins: Plugin[] = [];
  for (const option of definition.plugins) {
    plugins.push(...(await flattenPlugins(option)));
  }
  return plugins;
}

async function flattenPlugins(option: PluginOption): Promise<Plugin[]> {
  const resolved = await option;
  if (!resolved) return [];
  if (Array.isArray(resolved)) {
    const nested = await Promise.all(resolved.map((entry) => flattenPlugins(entry)));
    return nested.flat();
  }
  return [resolved];
}

export async function writeJson(path: string, value: GdanskManifest | GdanskDevelopmentManifest): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, `${JSON.stringify(value)}\n`, "utf8");
}

export function widgetRelativeEntry(root: string, entry: string): string {
  return toPosixPath(relative(resolve(root, "widgets"), entry));
}
