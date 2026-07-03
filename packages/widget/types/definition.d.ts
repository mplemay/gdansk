import type { RenderOptions, VitePluginReference, VitePluginReferenceOptions, WidgetDefinition } from "./types";
export declare function vitePlugin(specifier: string, options?: VitePluginReferenceOptions): VitePluginReference;
export declare function render(options: RenderOptions): WidgetDefinition;
export declare function assertWidgetDefinition(value: unknown, entry?: string): WidgetDefinition;
