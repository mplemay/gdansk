import type { InlineConfig, UserConfig } from "vite";
export interface GdanskPluginOptions {
  assets?: string;
  root?: string;
  widgetsRoot?: string;
  host?: string;
  port?: number;
}
export interface ResolvedGdanskOptions {
  generatedDir: string;
  generatedDirPath: string;
  host: string;
  outDir: string;
  outDirPath: string;
  root: string;
  ssrEndpoint: string;
  port: number;
  widgetsRoot: string;
  widgetsRootPath: string;
}
export interface WidgetDefinition {
  clientCss: string;
  clientDevEntry: string;
  clientEntry: string;
  clientSource: string;
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
  server: string;
  widgets: Record<string, ManifestWidget>;
}
export interface GdanskRuntimeMetadata {
  assetOrigin: string;
  mode: "development" | "production";
  ssrEndpoint: string;
  ssrOrigin: string;
  viteOrigin: string | null;
  widgets: Record<string, GdanskRuntimeWidget>;
}
export interface GdanskRuntimeWidget {
  clientPath: string;
}
export interface GdanskRenderRequest {
  assetBaseUrl?: string;
  component?: string;
  widget?: string;
}
export interface GdanskRenderResponse {
  body: string;
  head: string[];
}
export type GdanskRenderFunction = (widgetKey: string) => Promise<GdanskRenderResponse> | GdanskRenderResponse;
export interface GdanskPreparedProject {
  ssrEntry: string;
  widgets: WidgetDefinition[];
}
export interface GdanskServerOptions {
  manifest: GdanskManifest;
  options: ResolvedGdanskOptions;
  render: GdanskRenderFunction;
  widgets: WidgetDefinition[];
}
export interface GdanskServerHandle {
  close(): Promise<void>;
  origin: string;
  port: number;
}
export interface GdanskRuntime {
  build(): Promise<GdanskManifest>;
  close(): Promise<void>;
  manifestPath: string;
  options: ResolvedGdanskOptions;
  startDev(): Promise<GdanskRuntimeMetadata>;
  startProductionServer(): Promise<GdanskRuntimeMetadata>;
  widgets: WidgetDefinition[];
}
export type LoadedProjectConfig = InlineConfig | UserConfig;
