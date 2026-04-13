import type { IncomingMessage, ServerResponse } from "node:http";

import type { ViteDevServer } from "vite";

import { collectCSSFromModuleGraph } from "./css";
import { classifyRenderError, createSSRErrorPayload, formatSSRError } from "./ssr-errors";
import type {
  GdanskManifest,
  GdanskSSRErrorDiagnostic,
  GdanskSSRErrorPayload,
  GdanskRenderFunction,
  GdanskRenderRequest,
  GdanskRenderResponse,
  GdanskSSRResponsePayload,
  ResolvedGdanskOptions,
  WidgetDefinition,
} from "./types";

export const HEALTH_ENDPOINT = "/health";

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
        logError: (diagnostic) => {
          server.config.logger.error(formatSSRError(diagnostic, server.config.root));
        },
        render,
        requestBody,
        viteServer: server,
        widgets,
      });

      writeJson(res, result.status, result.payload);
    } catch (error) {
      const diagnostic = classifyRenderError(error);
      server.config.logger.error(formatSSRError(diagnostic, server.config.root));
      writeJson(res, 500, createSSRErrorPayload(toPublicSSRError(diagnostic)));
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
  logError,
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
      payload: createSSRErrorPayload({
        hint: 'Send a JSON body like {"widget":"hello"} or {"component":"hello"}.',
        message: getErrorMessage(error),
        type: "invalid_json",
      }),
      status: 400,
    };
  }

  const widgetKey = payload.widget ?? payload.component;

  if (!widgetKey) {
    return {
      payload: createSSRErrorPayload({
        hint: 'Include either "widget" or "component" in the SSR request body.',
        message: 'Request body must include "widget" or "component"',
        type: "invalid_request",
      }),
      status: 400,
    };
  }

  const widget = widgets.find((candidate) => candidate.key === widgetKey);

  if (!widget) {
    return {
      payload: createSSRErrorPayload({
        hint: "Ensure the widget key matches a registered Ship.widget(...) path and the frontend manifest contains that widget.",
        message: `Unknown widget: ${widgetKey}`,
        type: "unknown_widget",
        widget: widgetKey,
      }),
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
    const diagnostic = classifyRenderError(error, widget.key);
    logError?.(diagnostic);

    return {
      payload: createSSRErrorPayload(toPublicSSRError(diagnostic)),
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

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function toPublicSSRError(diagnostic: GdanskSSRErrorDiagnostic): GdanskSSRErrorPayload {
  const { hint, message, source, type, widget } = diagnostic;
  return { ...(hint ? { hint } : {}), message, ...(source ? { source } : {}), type, ...(widget ? { widget } : {}) };
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
