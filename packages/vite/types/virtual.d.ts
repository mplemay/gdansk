import type { Plugin } from "vite";

import type { GdanskPreparedProject, ResolvedGdanskOptions } from "./types";
export declare const GDANSK_DEV_CLIENT_PREFIX = "/@gdansk/client";
export declare const GDANSK_SSR_ENTRY_ID = "virtual:gdansk/ssr-entry";
export declare function createGdanskVirtualModulesPlugin(
  options: ResolvedGdanskOptions,
  prepared: GdanskPreparedProject,
): Plugin;
export declare function createClientDevEntry(key: string): string;
export declare function createClientModuleId(key: string): string;
export declare function createResolvedClientModuleId(key: string): string;
export declare function resolveVirtualModuleId(
  options: ResolvedGdanskOptions,
  prepared: GdanskPreparedProject,
  id: string,
  importer?: string,
): string | null;
export declare function loadVirtualModule(
  options: ResolvedGdanskOptions,
  prepared: GdanskPreparedProject,
  id: string,
): string | null;
