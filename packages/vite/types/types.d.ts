import type { InlineConfig, UserConfig } from "vite";
export interface RefreshConfig {
  paths: string | string[];
}
export interface GdanskPluginOptions {
  buildDirectory?: string;
  refresh?: boolean | string | string[] | RefreshConfig | RefreshConfig[];
  root?: string;
  widgetsDirectory?: string;
  host?: string;
  port?: number;
}
export interface ResolvedGdanskOptions {
  buildDirectory: string;
  buildDirectoryPath: string;
  host: string;
  root: string;
  port: number;
  widgetsDirectory: string;
  widgetsDirectoryPath: string;
}
export interface WidgetDefinition {
  clientCss: string;
  clientDevEntry: string;
  clientEntry: string;
  clientModuleId: string;
  entry: string;
  key: string;
  widgetPath: string;
}
export interface ManifestWidget {
  client: string;
  css: string[];
  entry: string;
}
export interface GdanskManifest {
  outDir: string;
  root: string;
  widgets: Record<string, ManifestWidget>;
}
export interface GdanskDevRuntimeMetadata {
  mode: "development";
  viteOrigin: string;
  widgets: Record<string, GdanskRuntimeWidget>;
}
export interface GdanskRuntimeWidget {
  clientPath: string;
}
export interface GdanskPreparedProject {
  widgets: WidgetDefinition[];
}
export interface GdanskRuntime {
  build(): Promise<GdanskManifest>;
  close(): Promise<void>;
  loadOrBuildManifest(): Promise<GdanskManifest>;
  manifestPath: string;
  options: ResolvedGdanskOptions;
  startDev(): Promise<GdanskDevRuntimeMetadata>;
  widgets: WidgetDefinition[];
}
export type LoadedProjectConfig = InlineConfig | UserConfig;
