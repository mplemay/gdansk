export { assertWidgetDefinition, render, vitePlugin } from "./definition";
export type { GdanskDevelopmentManifest, GdanskManifest, ManifestWidget, Metadata, RenderOptions, VitePluginReference, VitePluginReferenceOptions, WidgetDefinition, WidgetViteConfig, } from "./types";
export declare function buildProject(root: string, outDirectory: string): Promise<unknown>;
export declare function startDevelopment(options: {
    host: string;
    manifest: string;
    port: number;
    root: string;
}): Promise<never>;
