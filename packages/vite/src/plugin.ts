import { mergeConfig, type Plugin, type PluginOption, type UserConfig, type ViteDevServer } from "vite";

import { createBuildConfig } from "./build";
import { prepareProject, resolveOptions } from "./context";
import { resolveViteOrigin } from "./css";
import {
  createRefreshPlugin,
  mergeAliasConfig,
  resolveDevelopmentServerConfig,
  warmupWidgetEntries,
} from "./development";
import { installDevRenderMiddleware } from "./render";
import type { GdanskPluginOptions, GdanskPreparedProject, ResolvedGdanskOptions } from "./types";
import { loadVirtualModule, resolveVirtualModuleId } from "./virtual";

type GdanskDevServerMetadata = {
  renderEndpoint: string;
  renderOrigin: string;
};

type GdanskDevServer = ViteDevServer & {
  __gdansk?: GdanskDevServerMetadata;
};

export function gdansk(options: GdanskPluginOptions = {}): PluginOption {
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

  const corePlugin: Plugin = {
    async config(config, env) {
      resolved = resolveOptions(options, config.root);
      const sharedConfig = createSharedConfig(config, options, resolved);

      if (env.command === "build") {
        const project = await ensurePrepared(config.root);
        return mergeConfig(sharedConfig, createBuildConfig(resolved, project));
      }

      return sharedConfig;
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

      installDevRenderMiddleware({
        options: resolvedOptions,
        server,
        renderEntry: project.renderEntryId,
        widgets: project.widgets,
      });

      const updateMetadata = (): void => {
        (server as GdanskDevServer).__gdansk = {
          renderEndpoint: resolvedOptions.renderEndpoint,
          renderOrigin: resolveViteOrigin(server),
        };
      };

      const warmupWidgets = (): void => {
        void warmupWidgetEntries(server, project.widgets);
      };

      const clearMetadata = (): void => {
        delete (server as GdanskDevServer).__gdansk;
      };

      if (server.httpServer?.listening) {
        updateMetadata();
        warmupWidgets();
      } else {
        server.httpServer?.once("listening", updateMetadata);
        server.httpServer?.once("listening", warmupWidgets);
      }

      server.httpServer?.once("close", clearMetadata);
    },
  };

  return [corePlugin, createRefreshPlugin(options)];
}

function createSharedConfig(
  config: UserConfig,
  options: GdanskPluginOptions,
  resolved: ResolvedGdanskOptions,
): UserConfig {
  const server = resolveDevelopmentServerConfig(options, resolved);

  return {
    appType: "custom",
    resolve: {
      ...(config.resolve ?? {}),
      alias: mergeAliasConfig(config.resolve?.alias, resolved.root),
    },
    ...(server
      ? {
          server: {
            ...(config.server ?? {}),
            ...server,
          },
        }
      : {}),
  };
}
