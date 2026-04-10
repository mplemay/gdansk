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

export function installDevSSRMiddleware({ options, server, ssrEntry, widgets }: InstallDevSSRMiddlewareOptions): void {
  server.middlewares.use(HEALTH_ENDPOINT, (req, res, next) => {
    if (req.method !== "GET") {
      next();
      return;
    }

    writeJson(res, 200, { status: "OK" });
  });

  server.middlewares.use(options.ssrEndpoint, async (req, res, next) => {
    if (req.method !== "POST") {
      next();
      return;
    }

    try {
      const requestBody = await readRequestBody(req);
      const render = await loadRenderFunction(server, ssrEntry);
      const result = await processSSRRequest({
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

  server.config.logger.info(`Gdansk SSR dev endpoint: ${options.ssrEndpoint}`);

  server.httpServer?.once("listening", () => {
    server.config.logger.info("Warming up Gdansk SSR module graph...");

    server
      .ssrLoadModule(ssrEntry)
      .then(() => server.config.logger.info("Gdansk SSR module graph warmed up"))
      .catch((error) => {
        server.config.logger.warn(`Failed to warm up Gdansk SSR module graph: ${getErrorMessage(error)}`);
      });
  });
}

export async function importRenderFunction(path: string): Promise<GdanskRenderFunction> {
  const module = (await import(path)) as { default?: unknown };
  return resolveRenderFunction(module.default, path);
}

export async function processSSRRequest({
  manifest,
  render,
  requestBody,
  viteServer,
  widgets,
}: ProcessSSRRequestOptions): Promise<ProcessSSRRequestResult> {
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
    const head = viteServer
      ? [...collectCSSFromModuleGraph(viteServer, widget.entry), ...response.head]
      : [...createProductionCssHead(manifest, widget.key), ...response.head];

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
    throw new Error(`SSR entry "${entry}" must export a render function`);
  }

  return candidate as GdanskRenderFunction;
}

function validateRenderResponse(result: unknown): GdanskRenderResponse {
  if (!result || typeof result !== "object") {
    throw new Error("SSR render must return { head: string[], body: string }");
  }

  const body = Reflect.get(result, "body");
  const head = Reflect.get(result, "head");

  if (typeof body !== "string" || !Array.isArray(head) || !head.every((value) => typeof value === "string")) {
    throw new Error("SSR render must return { head: string[], body: string }");
  }

  return {
    body,
    head,
  };
}

function createProductionCssHead(manifest: GdanskManifest | undefined, widgetKey: string): string[] {
  if (!manifest) {
    return [];
  }

  const widget = manifest.widgets[widgetKey];

  if (!widget) {
    throw new Error(`Widget "${widgetKey}" is not present in the production manifest`);
  }

  return widget.css.map((href) => {
    return `<link rel="stylesheet" href="${toRootRelativeAssetPath(manifest.outDir, href)}">`;
  });
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
