import type { InlineConfig, Plugin, UserConfig, ViteDevServer } from "vite";

export interface GdanskPluginOptions {
  root?: string;
  widgetsRoot?: string;
  outDir?: string;
  host?: string;
  vitePort?: number;
  ssrPort?: number;
  ssrEndpoint?: string;
}

export interface ResolvedGdanskOptions {
  generatedDir: string;
  generatedDirPath: string;
  host: string;
  outDir: string;
  outDirPath: string;
  root: string;
  ssrEndpoint: string;
  ssrPort?: number;
  vitePort?: number;
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
  serverEntry: string;
  widgetPath: string;
}

export interface ManifestWidget {
  client: string;
  css: string | null;
  entry: string;
  server: string;
}

export interface GdanskManifest {
  outDir: string;
  root: string;
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
  component?: string;
  widget?: string;
}

export interface GdanskRenderResponse {
  body: string;
  head: string[];
}

export interface GdanskSidecarOptions {
  manifest?: GdanskManifest;
  mode: "development" | "production";
  options: ResolvedGdanskOptions;
  viteServer?: ViteDevServer;
  widgets: WidgetDefinition[];
}

export interface GdanskSidecarHandle {
  close(): Promise<void>;
  origin: string;
  port: number;
}

export interface GdanskRuntime {
  build(): Promise<GdanskManifest>;
  close(): Promise<void>;
  manifestPath: string;
  options: ResolvedGdanskOptions;
  runtimePath: string;
  startDev(): Promise<GdanskRuntimeMetadata>;
  startProductionServer(): Promise<GdanskRuntimeMetadata>;
  widgets: WidgetDefinition[];
}

export type ProjectPlugin = Plugin | Plugin[];
export type LoadedProjectConfig = InlineConfig | UserConfig;
