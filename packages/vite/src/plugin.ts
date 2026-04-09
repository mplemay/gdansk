import { rm } from "node:fs/promises";
import type { Plugin, ViteDevServer } from "vite";
import { discoverWidgets, resolveOptions } from "./context";
import { resolveViteOrigin } from "./css";
import { writeRuntimeMetadata } from "./build";
import { startSSRSidecar } from "./sidecar";
import type { GdanskPluginOptions, GdanskRuntimeMetadata, WidgetDefinition } from "./types";

export function gdansk(options: GdanskPluginOptions = {}): Plugin {
  let widgets: WidgetDefinition[] = [];

  return {
    async configResolved(config) {
      widgets = await discoverWidgets(resolveOptions(options, config.root));
    },
    name: "@gdansk/vite",
    async configureServer(server) {
      const resolved = resolveOptions(options, server.config.root);
      const sidecar = await startSSRSidecar({
        mode: "development",
        options: resolved,
        viteServer: server,
        widgets,
      });

      const metadata: GdanskRuntimeMetadata = {
        mode: "development",
        ssrEndpoint: resolved.ssrEndpoint,
        ssrOrigin: sidecar.origin,
        viteOrigin: resolveViteOrigin(server),
        widgets: widgets.map((widget) => widget.key),
      };

      await writeRuntimeMetadata(`${resolved.outDirPath}/runtime.json`, metadata);

      attachCleanup(server, async () => {
        await sidecar.close();
        await rm(`${resolved.outDirPath}/runtime.json`, { force: true });
      });

      server.config.logger.info(`Gdansk SSR dev endpoint: ${sidecar.origin}${resolved.ssrEndpoint}`);
    },
  };
}

function attachCleanup(server: ViteDevServer, callback: () => Promise<void>): void {
  const httpServer = server.httpServer;

  if (!httpServer) {
    return;
  }

  let cleanedUp = false;

  httpServer.once("close", () => {
    if (cleanedUp) {
      return;
    }

    cleanedUp = true;
    callback().catch(() => {});
  });
}
