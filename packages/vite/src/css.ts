import type { EnvironmentModuleNode, ViteDevServer } from "vite";

import { normalizePath } from "./path";

export function collectCSSFromModuleGraph(server: ViteDevServer, entry: string): string[] {
  const entryModule = resolveEntryModule(server, entry);

  if (!entryModule) {
    return [];
  }

  const cssModules = collectCSSModules(entryModule);

  if (cssModules.length === 0) {
    return [];
  }

  const origin = resolveViteOrigin(server);
  const base = server.config.base === "/" ? "" : server.config.base.replace(/\/$/, "");

  return cssModules.map(({ id, url }) => {
    const devId = id ? ` data-vite-dev-id="${id}"` : "";
    return `<link rel="stylesheet" href="${origin}${base}${url}"${devId}>`;
  });
}

export function resolveViteOrigin(server: ViteDevServer): string {
  const origin = server.resolvedUrls?.local[0] ?? server.resolvedUrls?.network[0];

  if (origin) {
    return new URL(origin).origin;
  }

  const protocol = server.config.server.https ? "https" : "http";
  return `${protocol}://${server.config.server.host ?? "127.0.0.1"}:${server.config.server.port ?? 5173}`;
}

function collectCSSModules(entryModule: EnvironmentModuleNode): Array<{ id: string | null; url: string }> {
  const cssModules: Array<{ id: string | null; url: string }> = [];
  const visited = new Set<EnvironmentModuleNode>();

  const walk = (mod: EnvironmentModuleNode): void => {
    if (visited.has(mod)) {
      return;
    }

    visited.add(mod);

    if (isCssRequest(mod.url)) {
      cssModules.push({ id: mod.id, url: mod.url });
      return;
    }

    for (const imported of mod.importedModules) {
      walk(imported);
    }
  };

  walk(entryModule);

  return cssModules;
}

function isCssRequest(url: string): boolean {
  return /\.(css|less|sass|scss|styl|stylus|pcss|postcss|sss)(?:$|\?)/.test(url);
}

function resolveEntryModule(server: ViteDevServer, entry: string): EnvironmentModuleNode | undefined {
  const moduleGraph = server.environments.ssr.moduleGraph;
  const normalized = normalizePath(entry);

  return moduleGraph.getModuleById(normalized) ?? moduleGraph.getModuleById(entry);
}
