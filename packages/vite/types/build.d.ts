import type { GdanskManifest, LoadedProjectConfig, ResolvedGdanskOptions, WidgetDefinition } from "./types";
export declare function buildWidgets(options: ResolvedGdanskOptions, widgets: WidgetDefinition[], config?: LoadedProjectConfig): Promise<GdanskManifest>;
export declare function readManifest(path: string): Promise<GdanskManifest>;
export declare function writeRuntimeMetadata(path: string, metadata: unknown): Promise<void>;
