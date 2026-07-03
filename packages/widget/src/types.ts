import type { ReactElement } from "react";
import type { UserConfig } from "vite";

export type Primitive = string | number | boolean;

export type Metadata = {
  metadataBase?: string;
  title?: string | { absolute?: string; default?: string; template?: string };
  description?: string;
  applicationName?: string;
  authors?: { name?: string; url?: string } | Array<{ name?: string; url?: string }>;
  generator?: string;
  keywords?: string | string[];
  referrer?: string;
  themeColor?: string | { color: string; media?: string } | Array<string | { color: string; media?: string }>;
  colorScheme?: string;
  viewport?: string | Record<string, Primitive>;
  creator?: string;
  publisher?: string;
  robots?: string | Record<string, Primitive | Record<string, Primitive>>;
  icons?: string | Record<string, unknown> | Array<string | Record<string, unknown>>;
  openGraph?: Record<string, unknown>;
  twitter?: Record<string, unknown>;
  verification?: Record<string, string | string[] | Record<string, string | string[]>>;
  manifest?: string;
  abstract?: string;
  category?: string;
  classification?: string;
  other?: Record<string, Primitive | Primitive[]>;
};

export type VitePluginReferenceOptions = {
  args?: unknown[];
  export?: string;
};

export type VitePluginReference = {
  readonly __gdanskVitePlugin: true;
  readonly args: unknown[];
  readonly export: string;
  readonly specifier: string;
};

export type WidgetViteConfig = Omit<
  UserConfig,
  "build" | "builder" | "configFile" | "environments" | "plugins" | "preview" | "root" | "server"
>;

export type RenderOptions = {
  metadata?: Metadata;
  plugins?: VitePluginReference[];
  vite?: WidgetViteConfig;
  widget: ReactElement;
};

export type WidgetDefinition = {
  readonly __gdanskWidget: true;
  readonly metadata: Metadata | undefined;
  readonly plugins: VitePluginReference[];
  readonly vite: WidgetViteConfig;
  readonly widget: ReactElement;
};

export type WidgetSource = {
  entry: string;
  key: string;
  widgetPath: string;
};

export type ManifestWidget = {
  entry: string;
  html: string;
};

export type GdanskManifest = {
  outDir: string;
  root: string;
  widgets: Record<string, ManifestWidget>;
};

export type DevelopmentManifestWidget = {
  entry: string;
  origin: string;
  page: string;
};

export type GdanskDevelopmentManifest = {
  root: string;
  widgets: Record<string, DevelopmentManifestWidget>;
};
