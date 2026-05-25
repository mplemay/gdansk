import { type Plugin, type UserConfig, type ViteDevServer } from "vite";

import type { GdanskPluginOptions, ResolvedGdanskOptions, WidgetDefinition } from "./types";
type AliasOption = NonNullable<NonNullable<UserConfig["resolve"]>["alias"]>;
export declare function mergeAliasConfig(alias: AliasOption | undefined, root: string): AliasOption;
export declare function resolveDevelopmentServerConfig(
  options: GdanskPluginOptions,
  resolved: ResolvedGdanskOptions,
): UserConfig["server"] | undefined;
export declare function createRefreshPlugin(options?: GdanskPluginOptions): Plugin;
export declare function warmupWidgetEntries(server: ViteDevServer, widgets: WidgetDefinition[]): Promise<void>;
export declare function normalizeRefreshConfig(refresh: GdanskPluginOptions["refresh"]): Array<{
  paths: string[];
}>;
export declare function resolveRefreshPaths(refresh: GdanskPluginOptions["refresh"], root: string): string[];
export {};
