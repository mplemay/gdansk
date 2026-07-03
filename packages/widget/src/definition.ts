import { isValidElement } from "react";

import type {
  RenderOptions,
  VitePluginReference,
  VitePluginReferenceOptions,
  WidgetDefinition,
} from "./types";

const FORBIDDEN_VITE_KEYS = new Set([
  "build",
  "builder",
  "configFile",
  "environments",
  "plugins",
  "preview",
  "root",
  "server",
]);

export function vitePlugin(
  specifier: string,
  options: VitePluginReferenceOptions = {},
): VitePluginReference {
  if (!specifier.trim()) {
    throw new Error("Gdansk Vite plugin specifier must not be empty.");
  }

  return Object.freeze({
    __gdanskVitePlugin: true as const,
    args: [...(options.args ?? [])],
    export: options.export ?? "default",
    specifier,
  });
}

export function render(options: RenderOptions): WidgetDefinition {
  if (!isValidElement(options.widget)) {
    throw new Error("Gdansk render() requires widget to be a React element.");
  }

  for (const key of Object.keys(options.vite ?? {})) {
    if (FORBIDDEN_VITE_KEYS.has(key)) {
      throw new Error(`Gdansk owns the Vite ${JSON.stringify(key)} option.`);
    }
  }

  for (const plugin of options.plugins ?? []) {
    if (!plugin || plugin.__gdanskVitePlugin !== true) {
      throw new Error("Gdansk render() plugins must be created with vitePlugin().");
    }
  }

  return Object.freeze({
    __gdanskWidget: true as const,
    metadata: options.metadata,
    plugins: [...(options.plugins ?? [])],
    vite: { ...(options.vite ?? {}) },
    widget: options.widget,
  });
}

export function assertWidgetDefinition(value: unknown, entry = "widget"): WidgetDefinition {
  if (
    typeof value !== "object" ||
    value === null ||
    !("__gdanskWidget" in value) ||
    value.__gdanskWidget !== true ||
    !("widget" in value) ||
    !isValidElement(value.widget)
  ) {
    throw new Error(`${entry} must default-export a function that returns render({...}).`);
  }
  return value as WidgetDefinition;
}
