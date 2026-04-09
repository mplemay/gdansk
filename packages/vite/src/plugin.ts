import { rm } from "node:fs/promises";
import type { Plugin, ViteDevServer } from "vite";
import { buildWidgets, writeRuntimeMetadata } from "./build";
import { ensureNoopEntry, loadUserViteConfig, prepareWidgets, resolveOptions } from "./context";
import { resolveViteOrigin } from "./css";
import type { GdanskPluginOptions, GdanskRuntimeMetadata, ResolvedGdanskOptions, WidgetDefinition } from "./types";

export function gdansk(options: GdanskPluginOptions = {}): Plugin {
  let resolved: ResolvedGdanskOptions | undefined;
  let widgets: WidgetDefinition[] = [];

  return {
    async config(config, env) {
      resolved = resolveOptions(options, config.root);

      if (env.command !== "build") {
        return {
          appType: "custom",
        };
      }

      const noopEntry = await ensureNoopEntry(resolved);

      return {
        appType: "custom",
        build: {
          copyPublicDir: false,
          emptyOutDir: false,
          outDir: resolved.outDir,
          rollupOptions: {
            input: noopEntry,
            output: {
              entryFileNames: "__gdansk_noop__.js",
              inlineDynamicImports: true,
            },
          },
        },
      };
    },
    async configResolved(config) {
      resolved = resolveOptions(options, config.root);
      widgets = await prepareWidgets(resolved);
    },
    name: "@gdansk/vite",
    async configureServer(server) {
      const resolvedOptions = resolved ?? resolveOptions(options, server.config.root);
      const { startSSRSidecar } = await import("./sidecar");
      let metadata: GdanskRuntimeMetadata | undefined;
      const sidecar = await startSSRSidecar({
        mode: "development",
        options: resolvedOptions,
        getRuntime: () => metadata,
        viteServer: server,
        widgets,
      });

      metadata = {
        assetOrigin: resolveViteOrigin(server),
        mode: "development",
        ssrEndpoint: resolvedOptions.ssrEndpoint,
        ssrOrigin: sidecar.origin,
        viteOrigin: resolveViteOrigin(server),
        widgets: Object.fromEntries(widgets.map((widget) => [widget.key, { clientPath: widget.clientDevEntry }])),
      };

      await writeRuntimeMetadata(`${resolvedOptions.outDirPath}/runtime.json`, metadata);

      attachCleanup(server, async () => {
        await sidecar.close();
        await rm(`${resolvedOptions.outDirPath}/runtime.json`, { force: true });
      });

      server.config.logger.info(`Gdansk SSR dev endpoint: ${sidecar.origin}${resolvedOptions.ssrEndpoint}`);
    },
    async closeBundle() {
      if (!resolved) {
        return;
      }

      const config = await loadUserViteConfig(resolved, "build");
      await buildWidgets(resolved, widgets, config);
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
