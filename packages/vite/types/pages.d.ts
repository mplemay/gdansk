import type { GdanskPreparedPageProject, ResolvedGdanskPageOptions } from "./types";
export declare const GDANSK_PAGE_DEV_ENTRY = "/@gdansk/pages/app.tsx";
export declare function createPageModuleId(): string;
export declare function createResolvedPageModuleId(): string;
export declare function resolvePageVirtualModuleId(
  options: ResolvedGdanskPageOptions,
  id: string,
  importer?: string,
): string | null;
export declare function loadPageVirtualModule(
  options: ResolvedGdanskPageOptions,
  prepared: GdanskPreparedPageProject,
  id: string,
): string | null;
