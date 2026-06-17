import type { UserConfig } from "vite";
import type { GdanskManifest, GdanskPreparedProject, LoadedProjectConfig, ResolvedGdanskOptions } from "./types";
export declare function createBuildConfig(options: ResolvedGdanskOptions, prepared: GdanskPreparedProject): UserConfig;
export declare function buildWidgets(options: ResolvedGdanskOptions, prepared: GdanskPreparedProject, config?: LoadedProjectConfig): Promise<GdanskManifest>;
export declare function readManifest(path: string): Promise<GdanskManifest>;
