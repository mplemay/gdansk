import type { IncomingMessage, ServerResponse } from "node:http";

import type { ViteDevServer } from "vite";

import { collectCSSFromModuleGraph } from "./css";
import type {
  GdanskManifest,
  GdanskRenderFunction,
  GdanskRenderRequest,
  GdanskRenderResponse,
  ResolvedGdanskOptions,
  WidgetDefinition,
} from "./types";

export const HEALTH_ENDPOINT = "/health";

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

export function installDevRenderMiddleware({
  options,
  server,
  renderEntry,
  widgets,
}: InstallDevRenderMiddlewareOptions): void {
  server.middlewares.use(HEALTH_ENDPOINT, (req, res, next) => {
    if (req.method !== "GET") {
      next();
      return;
    }

    writeJson(res, 200, { status: "OK" });
  });

  server.middlewares.use(options.renderEndpoint, async (req, res, next) => {
    if (req.method !== "POST") {
      next();
      return;
    }

    try {
      const requestBody = await readRequestBody(req);
      const render = await loadRenderFunction(server, renderEntry);
      const result = await processRenderRequest({
        render,
        requestBody,
        viteServer: server,
        widgets,
      });

      writeJson(res, result.status, result.payload);
    } catch (error) {
      writeJson(res, 500, createErrorResponse(error, "render_error"));
    }
  });

  server.config.logger.info(`Gdansk render dev endpoint: ${options.renderEndpoint}`);

  server.httpServer?.once("listening", () => {
    server.config.logger.info("Warming up Gdansk render module graph...");

    server
      .ssrLoadModule(renderEntry)
      .then(() => server.config.logger.info("Gdansk render module graph warmed up"))
      .catch((error) => {
        server.config.logger.warn(`Failed to warm up Gdansk render module graph: ${getErrorMessage(error)}`);
      });
  });
}

export async function importRenderFunction(path: string): Promise<GdanskRenderFunction> {
  const module = (await import(path)) as { default?: unknown };
  return resolveRenderFunction(module.default, path);
}

export async function processRenderRequest({
  manifest,
  render,
  requestBody,
  viteServer,
  widgets,
}: ProcessRenderRequestOptions): Promise<ProcessRenderRequestResult> {
  let payload: GdanskRenderRequest;

  try {
    payload = JSON.parse(requestBody) as GdanskRenderRequest;
  } catch (error) {
    return {
      payload: createErrorResponse(error, "invalid_json"),
      status: 400,
    };
  }

  const widgetKey = payload.widget ?? payload.component;

  if (!widgetKey) {
    return {
      payload: createErrorResponse('Request body must include "widget" or "component"', "invalid_request"),
      status: 400,
    };
  }

  const widget = widgets.find((candidate) => candidate.key === widgetKey);

  if (!widget) {
    return {
      payload: createErrorResponse(`Unknown widget: ${widgetKey}`, "unknown_widget"),
      status: 404,
    };
  }

  try {
    const rendered = await Promise.resolve(render(widget.key));
    const response = validateRenderResponse(rendered);
    const assetBaseUrl = payload.assetBaseUrl;
    const head = viteServer
      ? [...collectCSSFromModuleGraph(viteServer, widget.entry), ...response.head]
      : [...createProductionCssHead(assetBaseUrl, manifest, widget.key), ...response.head];

    return {
      payload: {
        body: response.body,
        head,
      },
      status: 200,
    };
  } catch (error) {
    return {
      payload: createErrorResponse(error, "render_error"),
      status: 500,
    };
  }
}

async function loadRenderFunction(server: ViteDevServer, entry: string): Promise<GdanskRenderFunction> {
  const module = (await server.ssrLoadModule(entry)) as { default?: unknown };
  return resolveRenderFunction(module.default, entry);
}

function resolveRenderFunction(candidate: unknown, entry: string): GdanskRenderFunction {
  if (typeof candidate !== "function") {
    throw new Error(`Render entry "${entry}" must export a render function`);
  }

  return candidate as GdanskRenderFunction;
}

function validateRenderResponse(result: unknown): GdanskRenderResponse {
  if (!result || typeof result !== "object") {
    throw new Error("Render output must return { head: string[], body: string }");
  }

  const body = Reflect.get(result, "body");
  const head = Reflect.get(result, "head");

  if (typeof body !== "string" || !Array.isArray(head) || !head.every((value) => typeof value === "string")) {
    throw new Error("Render output must return { head: string[], body: string }");
  }

  return {
    body,
    head,
  };
}

function createProductionCssHead(
  assetBaseUrl: string | undefined,
  manifest: GdanskManifest | undefined,
  widgetKey: string,
): string[] {
  if (!manifest) {
    return [];
  }

  const widget = manifest.widgets[widgetKey];

  if (!widget) {
    throw new Error(`Widget "${widgetKey}" is not present in the production manifest`);
  }

  return widget.css.map((href) => {
    if (assetBaseUrl) {
      return `<link rel="stylesheet" href="${toAbsoluteAssetPath(assetBaseUrl, manifest.outDir, href)}">`;
    }

    return `<link rel="stylesheet" href="${toRootRelativeAssetPath(manifest.outDir, href)}">`;
  });
}

function toAbsoluteAssetPath(assetBaseUrl: string, outDir: string, href: string): string {
  return new URL(stripOutDirPrefix(outDir, href), `${assetBaseUrl.replace(/\/+$/g, "")}/`).toString();
}

function toRootRelativeAssetPath(outDir: string, href: string): string {
  const normalizedOutDir = outDir.replace(/^\/+|\/+$/g, "");
  const normalizedPath = stripOutDirPrefix(outDir, href);
  return `/${[normalizedOutDir, normalizedPath].filter(Boolean).join("/")}`;
}

function stripOutDirPrefix(outDir: string, href: string): string {
  const normalized = href.replace(/^\/+/, "");
  const prefix = `${outDir.replace(/^\/+|\/+$/g, "")}/`;

  return normalized.startsWith(prefix) ? normalized.slice(prefix.length) : normalized;
}

function createErrorResponse(error: unknown, type: GdanskErrorResponse["error"]["type"]): GdanskErrorResponse {
  return {
    error: {
      message: getErrorMessage(error),
      type,
    },
  };
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function readRequestBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = "";

    req.on("data", (chunk) => {
      data += chunk;
    });
    req.on("end", () => {
      resolve(data);
    });
    req.on("error", reject);
  });
}

function writeJson(res: ServerResponse, status: number, payload: unknown): void {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(payload));
}
