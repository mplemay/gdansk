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
type ProcessRenderRequestOptions = {
  manifest?: GdanskManifest;
  render: GdanskRenderFunction;
  requestBody: string;
  viteServer?: ViteDevServer;
  widgets: WidgetDefinition[];
};
type ProcessRenderRequestResult = {
  payload: GdanskResponsePayload;
  status: 200 | 400 | 404 | 500;
};
type InstallDevRenderMiddlewareOptions = {
  options: ResolvedGdanskOptions;
  server: ViteDevServer;
  renderEntry: string;
  widgets: WidgetDefinition[];
};
export declare function installDevRenderMiddleware({
  options,
  server,
  renderEntry,
  widgets,
}: InstallDevRenderMiddlewareOptions): void;
export declare function importRenderFunction(path: string): Promise<GdanskRenderFunction>;
export declare function processRenderRequest({
  manifest,
  render,
  requestBody,
  viteServer,
  widgets,
}: ProcessRenderRequestOptions): Promise<ProcessRenderRequestResult>;
export {};
