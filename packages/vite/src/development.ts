import { matchesGlob, resolve } from "node:path";

import { normalizePath, type Alias, type Plugin, type UserConfig, type ViteDevServer } from "vite";

import { resolveOptions } from "./context";
import type { GdanskPluginOptions, RefreshConfig, ResolvedGdanskOptions, WidgetDefinition } from "./types";

type AliasOption = NonNullable<NonNullable<UserConfig["resolve"]>["alias"]>;

const DEFAULT_REFRESH_PATHS = ["../**/*.py", "../**/*.j2", "../**/*.jinja", "../**/*.jinja2"];

export function mergeAliasConfig(alias: AliasOption | undefined, root: string): AliasOption {
  if (Array.isArray(alias)) {
    return hasNamedAlias(alias, "@") ? alias : [...alias, { find: "@", replacement: root }];
  }

  if (typeof alias === "object" && alias !== null && "@" in alias) {
    return alias;
  }

  return {
    ...(alias ?? {}),
    "@": root,
  };
}

export function resolveDevelopmentServerConfig(
  options: GdanskPluginOptions,
  resolved: ResolvedGdanskOptions,
): UserConfig["server"] | undefined {
  if (typeof options.host === "undefined" && typeof options.port === "undefined") {
    return undefined;
  }

  return {
    host: resolved.host,
    port: resolved.port,
    strictPort: true,
  };
}

export function createRefreshPlugin(options: GdanskPluginOptions = {}): Plugin {
  return {
    apply: "serve",
    configureServer(server) {
      const resolved = resolveOptions(options, server.config.root);
      const normalizedRoot = normalizePath(resolved.root);
      const patterns = resolveRefreshPaths(options.refresh, resolved.root);
      let ready = false;

      if (patterns.length === 0) {
        return;
      }

      server.watcher.add(patterns);
      server.watcher.on("ready", () => {
        ready = true;
      });

      const handleChange = (file: string): void => {
        if (!ready) {
          return;
        }

        const normalized = normalizePath(file);

        if (!patterns.some((pattern) => matchesGlob(normalized, pattern))) {
          return;
        }

        const relativePath = normalized.startsWith(`${normalizedRoot}/`)
          ? normalized.slice(normalizedRoot.length + 1)
          : normalized;

        server.config.logger.info(`Gdansk full reload: ${relativePath}`);
        server.ws.send({ path: "*", type: "full-reload" });
      };

      server.watcher.on("add", handleChange);
      server.watcher.on("change", handleChange);
      server.watcher.on("unlink", handleChange);
    },
    name: "@gdansk/vite:refresh",
  };
}

export async function warmupWidgetEntries(server: ViteDevServer, widgets: WidgetDefinition[]): Promise<void> {
  const entries = new Set<string>();

  for (const widget of widgets) {
    entries.add(widget.entry);
    entries.add(widget.clientDevEntry);
  }

  await Promise.allSettled(
    [...entries].map(async (entry) => {
      await server.warmupRequest(entry);
    }),
  );

  await server.waitForRequestsIdle?.();
}

export function normalizeRefreshConfig(refresh: GdanskPluginOptions["refresh"]): Array<{ paths: string[] }> {
  if (!refresh) {
    return [];
  }

  if (refresh === true) {
    return [{ paths: [...DEFAULT_REFRESH_PATHS] }];
  }

  if (typeof refresh === "string") {
    return [{ paths: [refresh] }];
  }

  if (Array.isArray(refresh)) {
    if (refresh.length === 0) {
      return [];
    }

    if (refresh.every((entry) => typeof entry === "string")) {
      return [{ paths: [...refresh] }];
    }

    return refresh.map((entry) => normalizeRefreshEntry(entry as RefreshConfig));
  }

  return [normalizeRefreshEntry(refresh)];
}

export function resolveRefreshPaths(refresh: GdanskPluginOptions["refresh"], root: string): string[] {
  return normalizeRefreshConfig(refresh).flatMap((config) =>
    config.paths.map((pattern) => normalizePath(resolve(root, pattern))),
  );
}

function hasNamedAlias(aliases: Alias[], name: string): boolean {
  return aliases.some((alias) => alias.find === name);
}

function normalizeRefreshEntry(config: RefreshConfig): { paths: string[] } {
  return {
    paths: Array.isArray(config.paths) ? [...config.paths] : [config.paths],
  };
}
