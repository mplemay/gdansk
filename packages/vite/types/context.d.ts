import type {
  GdanskPreparedProject,
  GdanskPagePluginOptions,
  GdanskPluginOptions,
  LoadedProjectConfig,
  ResolvedGdanskPageOptions,
  ResolvedGdanskOptions,
  WidgetDefinition,
} from "./types";
export declare function resolveOptions(options?: GdanskPluginOptions, configRoot?: string): ResolvedGdanskOptions;
export declare function resolvePageOptions(
  options?: GdanskPagePluginOptions,
  configRoot?: string,
): ResolvedGdanskPageOptions;
export declare function discoverWidgets(options: ResolvedGdanskOptions): Promise<WidgetDefinition[]>;
export declare function loadUserViteConfig(
  options: ResolvedGdanskOptions,
  command: "build" | "serve",
): Promise<LoadedProjectConfig>;
export declare function prepareProject(options: ResolvedGdanskOptions): Promise<GdanskPreparedProject>;
export declare function pathExists(path: string): Promise<boolean>;
export declare function toPosixPath(path: string): string;
