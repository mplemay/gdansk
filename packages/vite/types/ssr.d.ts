import type { ViteDevServer } from "vite";

import type {
  GdanskManifest,
  GdanskSSRErrorDiagnostic,
  GdanskRenderFunction,
  GdanskSSRResponsePayload,
  ResolvedGdanskOptions,
  WidgetDefinition,
} from "./types";
export declare const HEALTH_ENDPOINT = "/health";
type ProcessSSRRequestOptions = {
  logError?: (diagnostic: GdanskSSRErrorDiagnostic) => void;
  manifest?: GdanskManifest;
  render: GdanskRenderFunction;
  requestBody: string;
  viteServer?: ViteDevServer;
  widgets: WidgetDefinition[];
};
type ProcessSSRRequestResult = {
  payload: GdanskSSRResponsePayload;
  status: 200 | 400 | 404 | 500;
};
type InstallDevSSRMiddlewareOptions = {
  options: ResolvedGdanskOptions;
  server: ViteDevServer;
  ssrEntry: string;
  widgets: WidgetDefinition[];
};
export declare function installDevSSRMiddleware({
  options,
  server,
  ssrEntry,
  widgets,
}: InstallDevSSRMiddlewareOptions): void;
export declare function importRenderFunction(path: string): Promise<GdanskRenderFunction>;
export declare function processSSRRequest({
  logError,
  manifest,
  render,
  requestBody,
  viteServer,
  widgets,
}: ProcessSSRRequestOptions): Promise<ProcessSSRRequestResult>;
export {};
