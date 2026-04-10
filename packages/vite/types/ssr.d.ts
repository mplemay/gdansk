import type { ViteDevServer } from "vite";

import type {
  GdanskManifest,
  GdanskRenderFunction,
  GdanskRenderResponse,
  ResolvedGdanskOptions,
  WidgetDefinition,
} from "./types";
export declare const HEALTH_ENDPOINT = "/health";
type GdanskErrorResponse = {
  error: {
    message: string;
    type: "invalid_json" | "invalid_request" | "render_error" | "unknown_widget";
  };
};
type GdanskResponsePayload = GdanskErrorResponse | GdanskRenderResponse;
type ProcessSSRRequestOptions = {
  manifest?: GdanskManifest;
  render: GdanskRenderFunction;
  requestBody: string;
  viteServer?: ViteDevServer;
  widgets: WidgetDefinition[];
};
type ProcessSSRRequestResult = {
  payload: GdanskResponsePayload;
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
  manifest,
  render,
  requestBody,
  viteServer,
  widgets,
}: ProcessSSRRequestOptions): Promise<ProcessSSRRequestResult>;
export {};
