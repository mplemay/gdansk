import { assertWidgetDefinition, render } from "./definition";
import type { VitePluginReference, VitePluginReferenceOptions } from "./types";

const INERT_VITE_PLUGIN = Object.freeze({
  __gdanskVitePlugin: true as const,
  args: [],
  export: "default",
  specifier: "",
});

export { assertWidgetDefinition, render };

export function vitePlugin(
  _specifier: string,
  _options: VitePluginReferenceOptions = {},
): VitePluginReference {
  return INERT_VITE_PLUGIN;
}

export type {
  Metadata,
  RenderOptions,
  VitePluginReference,
  VitePluginReferenceOptions,
  WidgetDefinition,
  WidgetViteConfig,
} from "./types";
