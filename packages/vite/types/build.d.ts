import type { Plugin } from "vite";
import type { GdanskManifest, ResolvedGdanskOptions, WidgetDefinition } from "./types";
export declare function buildWidgets(options: ResolvedGdanskOptions, widgets: WidgetDefinition[], plugins: Plugin[]): Promise<GdanskManifest>;
export declare function readManifest(path: string): Promise<GdanskManifest>;
export declare function writeRuntimeMetadata(path: string, metadata: unknown): Promise<void>;
