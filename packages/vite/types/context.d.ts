import type { Plugin } from "vite";
import type { GdanskPluginOptions, ResolvedGdanskOptions, WidgetDefinition } from "./types";
export declare function resolveOptions(options?: GdanskPluginOptions, configRoot?: string): ResolvedGdanskOptions;
export declare function discoverWidgets(options: ResolvedGdanskOptions): Promise<WidgetDefinition[]>;
export declare function loadProjectPlugins(options: ResolvedGdanskOptions): Promise<Plugin[]>;
export declare function pathExists(path: string): Promise<boolean>;
export declare function toPosixPath(path: string): string;
