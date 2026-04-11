import type { Plugin, ViteDevServer } from "vite";

import { createBuildConfig } from "./build";
import { prepareProject, resolveOptions } from "./context";
import { resolveViteOrigin } from "./css";
import { installDevSSRMiddleware } from "./ssr";
import type { GdanskPluginOptions, GdanskPreparedProject, ResolvedGdanskOptions } from "./types";
import { loadVirtualModule, resolveVirtualModuleId } from "./virtual";

type GdanskDevServerMetadata = {
  ssrEndpoint: string;
  ssrOrigin: string;
};

type GdanskDevServer = ViteDevServer & {
  __gdansk?: GdanskDevServerMetadata;
};

export function gdansk(options: GdanskPluginOptions = {}): Plugin {
  let prepared: GdanskPreparedProject | undefined;
  let preparePromise: Promise<GdanskPreparedProject> | undefined;
  let resolved: ResolvedGdanskOptions | undefined;

  const ensurePrepared = (configRoot?: string): Promise<GdanskPreparedProject> => {
    resolved = resolveOptions(options, configRoot);
    preparePromise ??= prepareProject(resolved).then((result) => {
      prepared = result;
      return result;
    });
    return preparePromise;
  };

  return {
    async config(config, env) {
      resolved = resolveOptions(options, config.root);

      if (env.command !== "build") {
        return {
          appType: "custom",
        };
      }

      const project = await ensurePrepared(config.root);

      return createBuildConfig(resolved, project);
    },
    async configResolved(config) {
      await ensurePrepared(config.root);
    },
    async load(id) {
      const project = prepared ?? (await ensurePrepared(resolved?.root));
      const resolvedOptions = resolved ?? resolveOptions(options);
      return loadVirtualModule(resolvedOptions, project, id);
    },
    name: "@gdansk/vite",
    async resolveId(id, importer) {
      const project = prepared ?? (await ensurePrepared(resolved?.root));
      const resolvedOptions = resolved ?? resolveOptions(options);
      return resolveVirtualModuleId(resolvedOptions, project, id, importer);
    },
    async configureServer(server) {
      const project = prepared ?? (await ensurePrepared(server.config.root));
      const resolvedOptions = resolved ?? resolveOptions(options, server.config.root);

      installDevSSRMiddleware({
        options: resolvedOptions,
        server,
        ssrEntry: project.ssrEntryId,
        widgets: project.widgets,
      });

      const updateMetadata = (): void => {
        (server as GdanskDevServer).__gdansk = {
          ssrEndpoint: resolvedOptions.ssrEndpoint,
          ssrOrigin: resolveViteOrigin(server),
        };
      };

      const clearMetadata = (): void => {
        delete (server as GdanskDevServer).__gdansk;
      };

      if (server.httpServer?.listening) {
        updateMetadata();
      } else {
        server.httpServer?.once("listening", updateMetadata);
      }

      server.httpServer?.once("close", clearMetadata);
    },
  };
}
