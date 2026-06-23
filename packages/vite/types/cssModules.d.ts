import type { Plugin, UserConfig } from "vite";
export declare function createSharedCssModulesConfig(): UserConfig["css"];
export declare function createGdanskCssModulesPlugin(): Plugin;
export declare function cssPathHasModuleTypes(cssPath: string): boolean;
