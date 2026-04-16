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
  ssrEndpoint: string;
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
  ssrEntryId: string;
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
