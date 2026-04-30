import type {
  GdanskPreparedProject,
  GdanskPluginOptions,
  LoadedProjectConfig,
  ResolvedGdanskOptions,
  WidgetDefinition,
} from "./types";
export declare function resolveOptions(options?: GdanskPluginOptions, configRoot?: string): ResolvedGdanskOptions;
export declare function resolveProductionBase(options: ResolvedGdanskOptions): string;
export declare function discoverWidgets(options: ResolvedGdanskOptions): Promise<WidgetDefinition[]>;
export declare function loadUserViteConfig(
  options: ResolvedGdanskOptions,
  command: "build" | "serve",
): Promise<LoadedProjectConfig>;
export declare function prepareProject(options: ResolvedGdanskOptions): Promise<GdanskPreparedProject>;
export declare function pathExists(path: string): Promise<boolean>;
export declare function toPosixPath(path: string): string;
