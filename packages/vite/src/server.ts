import { serve } from "@hono/node-server";
import { serveStatic } from "@hono/node-server/serve-static";
import { Hono } from "hono";

import { HEALTH_ENDPOINT, processSSRRequest } from "./ssr";
import { formatSSRError } from "./ssr-errors";
import type { GdanskServerHandle, GdanskServerOptions } from "./types";

export async function startGdanskServer(options: GdanskServerOptions): Promise<GdanskServerHandle> {
  const app = new Hono();
  const outDirPrefix = `/${options.options.buildDirectory.replace(/^\/+/, "")}`;

  app.get(HEALTH_ENDPOINT, (c) => c.json({ status: "OK" }));

  app.post(options.options.ssrEndpoint, async (c) => {
    const requestBody = await c.req.text();
    const result = await processSSRRequest({
      logError: (diagnostic) => {
        console.error(formatSSRError(diagnostic, options.options.root));
      },
      manifest: options.manifest,
      render: options.render,
      requestBody,
      widgets: options.widgets,
    });

    return c.json(result.payload, result.status);
  });

  app.use(
    `${outDirPrefix}/*`,
    serveStatic({
      onFound: (_, c) => {
        c.header("Access-Control-Allow-Origin", "*");
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
