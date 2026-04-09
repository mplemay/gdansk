import type { Plugin, ViteDevServer } from "vite";
import { buildWidgets } from "./build";
import { ensureNoopEntry, loadUserViteConfig, prepareWidgets, resolveOptions } from "./context";
import type { GdanskPluginOptions, ResolvedGdanskOptions, WidgetDefinition } from "./types";

type GdanskDevServerMetadata = {
  ssrEndpoint: string;
  ssrOrigin: string;
};

type GdanskDevServer = ViteDevServer & {
  __gdansk?: GdanskDevServerMetadata;
};

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
      const sidecar = await startSSRSidecar({
        mode: "development",
        options: resolvedOptions,
        viteServer: server,
        widgets,
      });
      (server as GdanskDevServer).__gdansk = {
        ssrEndpoint: resolvedOptions.ssrEndpoint,
        ssrOrigin: sidecar.origin,
      };

      attachCleanup(server, async () => {
        await sidecar.close();
        delete (server as GdanskDevServer).__gdansk;
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
