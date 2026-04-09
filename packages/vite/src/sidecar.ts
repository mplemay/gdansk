import { stat } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { serve } from "@hono/node-server";
import { serveStatic } from "@hono/node-server/serve-static";
import { Hono } from "hono";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { collectCSSFromModuleGraph } from "./css";
import type {
  GdanskManifest,
  GdanskRenderRequest,
  GdanskRenderResponse,
  GdanskSidecarHandle,
  GdanskSidecarOptions,
  ManifestWidget,
  WidgetDefinition,
} from "./types";

const RUNTIME_ENDPOINT = "/__gdansk_runtime";

export async function startSSRSidecar(options: GdanskSidecarOptions): Promise<GdanskSidecarHandle> {
  const app = new Hono();
  const widgetMap = new Map(options.widgets.map((widget) => [widget.key, widget]));
  const outDirPrefix = `/${options.options.outDir.replace(/^\/+/, "")}`;

  // The Python host polls this route until the runtime metadata is populated.
  app.get(RUNTIME_ENDPOINT, (c) => {
    const runtime = options.getRuntime?.();

    if (!runtime) {
      return c.json(
        { error: { message: "Frontend runtime metadata is not ready yet", type: "runtime_not_ready" } },
        503,
      );
    }

    return c.json(runtime);
  });

  app.post(options.options.ssrEndpoint, async (c) => {
    let payload: GdanskRenderRequest;

    try {
      payload = await c.req.json<GdanskRenderRequest>();
    } catch (error) {
      return c.json({ error: { message: getErrorMessage(error), type: "invalid_json" } }, 400);
    }

    const widgetKey = payload.widget ?? payload.component;

    if (!widgetKey) {
      return c.json({ error: { message: 'Request body must include "widget" or "component"', type: "invalid_request" } }, 400);
    }

    const widget = widgetMap.get(widgetKey);

    if (!widget) {
      return c.json({ error: { message: `Unknown widget: ${widgetKey}`, type: "unknown_widget" } }, 404);
    }

    try {
      const response =
        options.mode === "development"
          ? await renderDevelopmentWidget(widget, options)
          : await renderProductionWidget(widget, options, new URL(c.req.url).origin);

      return c.json(response);
    } catch (error) {
      return c.json({ error: { message: getErrorMessage(error), type: "render_error" } }, 500);
    }
  });

  app.use(
    `${outDirPrefix}/*`,
    serveStatic({
      onFound: (_, c) => {
        c.header("Cache-Control", "public, max-age=31536000, immutable");
      },
      root: options.options.root,
    }),
  );

  let resolvedPort = options.options.port;

  const server = await new Promise<ReturnType<typeof serve>>((resolveServer) => {
    const instance = serve(
      {
        fetch: app.fetch,
        hostname: options.options.host,
        port: options.options.port,
      },
      (info) => {
        resolvedPort = info.port;
        resolveServer(instance);
      },
    );
  });

  const origin = `http://${options.options.host}:${resolvedPort}`;

  return {
    close: () =>
      new Promise<void>((resolveClose, rejectClose) => {
        server.close((error) => {
          if (error) {
            rejectClose(error);
            return;
          }

          resolveClose();
        });
      }),
    origin,
    port: resolvedPort,
  };
}

async function renderDevelopmentWidget(
  widget: WidgetDefinition,
  options: GdanskSidecarOptions,
): Promise<GdanskRenderResponse> {
  if (!options.viteServer) {
    throw new Error("A Vite dev server is required in development mode");
  }

  const module = (await options.viteServer.ssrLoadModule(widget.entry)) as { default?: unknown };
  const component = getComponent(module.default, widget.key);

  return {
    body: renderToString(createElement(component)),
    head: collectCSSFromModuleGraph(options.viteServer, widget.entry),
  };
}

async function renderProductionWidget(
  widget: WidgetDefinition,
  options: GdanskSidecarOptions,
  assetOrigin: string,
): Promise<GdanskRenderResponse> {
  const manifest = getManifestWidget(options.manifest, widget.key);
  const module = (await importServerModule(resolve(options.options.root, manifest.server))) as { default?: unknown };
  const component = getComponent(module.default, widget.key);
  const href = manifest.css ? `${assetOrigin}/${manifest.css.replace(/^\/+/, "")}` : null;

  return {
    body: renderToString(createElement(component)),
    head: href ? [`<link rel="stylesheet" href="${href}">`] : [],
  };
}

function getComponent(component: unknown, widgetKey: string) {
  if (!component) {
    throw new Error(`Widget "${widgetKey}" must have a default export`);
  }

  return component as Parameters<typeof createElement>[0];
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function importServerModule(path: string): Promise<object> {
  const modified = await stat(path);
  return import(`${pathToFileURL(path).href}?t=${modified.mtimeMs}`) as Promise<object>;
}

function getManifestWidget(manifest: GdanskManifest | undefined, widgetKey: string): ManifestWidget {
  if (!manifest) {
    throw new Error("A production manifest is required before starting the SSR server");
  }

  const widget = manifest.widgets[widgetKey];

  if (!widget) {
    throw new Error(`Widget "${widgetKey}" is not present in the production manifest`);
  }

  return widget;
}
