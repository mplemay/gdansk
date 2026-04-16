import { dirname, relative, resolve, sep } from "node:path";

import type { Plugin } from "vite";

import type { GdanskPreparedProject, ResolvedGdanskOptions, WidgetDefinition } from "./types";

export const GDANSK_DEV_CLIENT_PREFIX = "/@gdansk/client";

const CLIENT_MODULE_PREFIX = "virtual:gdansk/client/";
const RESOLVED_VIRTUAL_PREFIX = "\0";
const SYNTHETIC_ROOT = "__gdansk_virtual__";

export function createGdanskVirtualModulesPlugin(
  options: ResolvedGdanskOptions,
  prepared: GdanskPreparedProject,
): Plugin {
  return {
    load(id) {
      return loadVirtualModule(options, prepared, id);
    },
    name: "@gdansk/vite:virtual-modules",
    resolveId(id, importer) {
      return resolveVirtualModuleId(options, prepared, id, importer);
    },
  };
}

export function createClientDevEntry(key: string): string {
  return `${GDANSK_DEV_CLIENT_PREFIX}/${key}.tsx`;
}

export function createClientModuleId(key: string): string {
  return `${CLIENT_MODULE_PREFIX}${key}`;
}

export function createResolvedClientModuleId(key: string): string {
  return `${RESOLVED_VIRTUAL_PREFIX}${createClientModuleId(key)}`;
}

export function resolveVirtualModuleId(
  options: ResolvedGdanskOptions,
  prepared: GdanskPreparedProject,
  id: string,
  importer?: string,
): string | null {
  const widgetByDevEntry = findWidgetByDevEntry(prepared.widgets, id);
  if (widgetByDevEntry) {
    return createResolvedClientModuleId(widgetByDevEntry.key);
  }

  const widgetByModuleId = findWidgetByModuleId(prepared.widgets, id);
  if (widgetByModuleId) {
    return createResolvedClientModuleId(widgetByModuleId.key);
  }

  if (!importer || !id.startsWith(".")) {
    return null;
  }

  const syntheticImporterPath = getSyntheticImporterPath(options, prepared, importer);
  if (!syntheticImporterPath) {
    return null;
  }

  return resolve(dirname(syntheticImporterPath), id);
}

export function loadVirtualModule(
  options: ResolvedGdanskOptions,
  prepared: GdanskPreparedProject,
  id: string,
): string | null {
  const widget = findWidgetByResolvedId(prepared.widgets, id);
  return widget ? createClientModuleSource(options, widget) : null;
}

function createClientModuleSource(options: ResolvedGdanskOptions, widget: WidgetDefinition): string {
  const syntheticPath = getSyntheticClientPath(options, widget.key);
  const sourceImport = createImportPath(syntheticPath, widget.entry);

  return [
    'import React from "react";',
    'import { createRoot, hydrateRoot } from "react-dom/client";',
    `import App from ${JSON.stringify(sourceImport)};`,
    "",
    'const root = document.getElementById("root");',
    "",
    "if (!root) {",
    "  throw new Error('Gdansk expected a #root element for widget hydration.');",
    "}",
    "",
    "const element = React.createElement(React.StrictMode, null, React.createElement(App));",
    "",
    "if (root.hasChildNodes()) {",
    "  hydrateRoot(root, element);",
    "} else {",
    "  createRoot(root).render(element);",
    "}",
    "",
  ].join("\n");
}

function createImportPath(from: string, to: string): string {
  const relativePath = toPosixPath(relative(dirname(from), to));
  return relativePath.startsWith(".") ? relativePath : `./${relativePath}`;
}

function findWidgetByDevEntry(widgets: WidgetDefinition[], id: string): WidgetDefinition | undefined {
  return widgets.find((widget) => widget.clientDevEntry === id);
}

function findWidgetByModuleId(widgets: WidgetDefinition[], id: string): WidgetDefinition | undefined {
  return widgets.find((widget) => widget.clientModuleId === id);
}

function findWidgetByResolvedId(widgets: WidgetDefinition[], id: string): WidgetDefinition | undefined {
  return widgets.find((widget) => createResolvedClientModuleId(widget.key) === id);
}

function getSyntheticClientPath(options: ResolvedGdanskOptions, key: string): string {
  return resolve(options.root, SYNTHETIC_ROOT, "client", key, "client.tsx");
}

function getSyntheticImporterPath(
  options: ResolvedGdanskOptions,
  prepared: GdanskPreparedProject,
  importer: string,
): string | null {
  const widget = findWidgetByResolvedId(prepared.widgets, importer);
  return widget ? getSyntheticClientPath(options, widget.key) : null;
}

function toPosixPath(path: string): string {
  return path.split(sep).join("/");
}
