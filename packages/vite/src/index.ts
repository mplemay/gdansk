import packageJson from "../package.json";

export const GDANSK_VERSION = packageJson.version;

export { gdansk as default, gdansk } from "./plugin";
export type { GdanskDevRuntimeMetadata, GdanskPluginOptions, RefreshConfig, ResolvedGdanskOptions } from "./types";
