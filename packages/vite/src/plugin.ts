import { resolve } from "node:path";

import type { Plugin, UserConfig, ViteDevServer } from "vite";

import { createBuildConfig, createPageBuildConfig } from "./build";
import { preparePageProject, prepareProject, resolveOptions, resolvePageOptions } from "./context";
import { resolveViteOrigin } from "./css";
import {
  createRefreshPlugin,
  mergeAliasConfig,
  resolveDevelopmentServerConfig,
  warmupPageEntries,
  warmupWidgetEntries,
} from "./development";
import { loadPageVirtualModule, resolvePageVirtualModuleId } from "./pages";
import type {
  GdanskPagePluginOptions,
  GdanskPluginOptions,
  GdanskPreparedPageProject,
  GdanskPreparedProject,
  ResolvedGdanskOptions,
  ResolvedGdanskPageOptions,
} from "./types";
import { loadVirtualModule, resolveVirtualModuleId } from "./virtual";
import { loadViteModule } from "./vite-runtime";

type GdanskDevServerMetadata = {
  viteOrigin: string;
};

type GdanskDevServer = ViteDevServer & {
  __gdansk?: GdanskDevServerMetadata;
};

export function gdansk(options: GdanskPluginOptions = {}): Array<{ name: string }> {
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
        const { mergeConfig } = await loadViteModule();
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

      const updateMetadata = (): void => {
        (server as GdanskDevServer).__gdansk = {
          viteOrigin: resolveViteOrigin(server),
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

export function gdanskPages(options: GdanskPagePluginOptions = {}): Array<{ name: string }> {
  let prepared: GdanskPreparedPageProject | undefined;
  let preparePromise: Promise<GdanskPreparedPageProject> | undefined;
  let resolved: ResolvedGdanskPageOptions | undefined;

  const ensurePrepared = (configRoot?: string): Promise<GdanskPreparedPageProject> => {
    resolved = resolvePageOptions(options, configRoot);
    preparePromise ??= preparePageProject(resolved).then((result) => {
      prepared = result;
      return result;
    });
    return preparePromise;
  };

  const corePlugin: Plugin = {
    async config(config, env) {
      resolved = resolvePageOptions(options, config.root);
      const sharedConfig = createSharedConfig(config, options, resolved, { pageTypes: true });

      if (env.command === "build") {
        await ensurePrepared(config.root);
        const { mergeConfig } = await loadViteModule();
        return mergeConfig(sharedConfig, createPageBuildConfig(resolved));
      }

      return sharedConfig;
    },
    async configResolved(config) {
      await ensurePrepared(config.root);
    },
    async load(id) {
      const project = prepared ?? (await ensurePrepared(resolved?.root));
      const pageOptions = resolved ?? resolvePageOptions(options);
      return loadPageVirtualModule(pageOptions, project, id);
    },
    name: "@gdansk/vite:pages",
    async resolveId(id, importer) {
      const pageOptions = resolved ?? resolvePageOptions(options);
      return resolvePageVirtualModuleId(pageOptions, id, importer);
    },
    async configureServer(server) {
      const project = prepared ?? (await ensurePrepared(server.config.root));
      resolved ??= resolvePageOptions(options, server.config.root);

      const updateMetadata = (): void => {
        (server as GdanskDevServer).__gdansk = {
          viteOrigin: resolveViteOrigin(server),
        };
      };

      const warmupPages = (): void => {
        void warmupPageEntries(server, project);
      };

      const clearMetadata = (): void => {
        delete (server as GdanskDevServer).__gdansk;
      };

      if (server.httpServer?.listening) {
        updateMetadata();
        warmupPages();
      } else {
        server.httpServer?.once("listening", updateMetadata);
        server.httpServer?.once("listening", warmupPages);
      }

      server.httpServer?.once("close", clearMetadata);
    },
  };

  return [corePlugin, createRefreshPlugin(options)];
}

function createSharedConfig(
  config: UserConfig,
  options: GdanskPluginOptions | GdanskPagePluginOptions,
  resolved: ResolvedGdanskOptions,
  extra: { pageTypes?: boolean } = {},
): UserConfig {
  const server = resolveDevelopmentServerConfig(options, resolved);
  const extraAliases: Record<string, string> = extra.pageTypes
    ? { "@types/gdansk": resolve(resolved.root, "types/gdansk") }
    : {};

  return {
    appType: "custom",
    resolve: {
      ...(config.resolve ?? {}),
      alias: mergeAliasConfig(config.resolve?.alias, resolved.root, extraAliases),
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
