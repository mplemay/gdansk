export { assertWidgetDefinition, render } from "./definition";
export type { GdanskDevelopmentManifest, GdanskManifest, ManifestWidget, Metadata, RenderOptions, WidgetDefinition, WidgetViteConfig, } from "./types";
export declare function buildProject(root: string, outDirectory: string): Promise<unknown>;
export declare function startDevelopment(options: {
    host: string;
    manifest: string;
    port: number;
    root: string;
}): Promise<never>;
