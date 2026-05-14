import type { Plugin, UserConfig, ViteDevServer } from "vite";

import type {
  GdanskPagePluginOptions,
  GdanskPluginOptions,
  GdanskPreparedPageProject,
  ResolvedGdanskOptions,
  WidgetDefinition,
} from "./types";
type AliasOption = NonNullable<NonNullable<UserConfig["resolve"]>["alias"]>;
export declare function mergeAliasConfig(
  alias: AliasOption | undefined,
  root: string,
  extraAliases?: Record<string, string>,
): AliasOption;
export declare function resolveDevelopmentServerConfig(
  options: GdanskPluginOptions,
  resolved: ResolvedGdanskOptions,
): UserConfig["server"] | undefined;
export declare function createRefreshPlugin(options?: GdanskPluginOptions): Plugin;
export declare function warmupWidgetEntries(server: ViteDevServer, widgets: WidgetDefinition[]): Promise<void>;
export declare function warmupPageEntries(server: ViteDevServer, project: GdanskPreparedPageProject): Promise<void>;
export declare function normalizeRefreshConfig(refresh: GdanskPluginOptions["refresh"]): Array<{
  paths: string[];
}>;
export declare function resolveRefreshPaths(
  refresh: GdanskPluginOptions["refresh"] | GdanskPagePluginOptions["refresh"],
  root: string,
): string[];
export {};
