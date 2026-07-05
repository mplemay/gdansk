import react from "@vitejs/plugin-react";
import { createServer, mergeConfig, type InlineConfig, type Plugin, type ViteDevServer } from "vite";

import { createGdanskCssModulesPlugin, createSharedCssModulesConfig } from "./cssModules";
import { renderDocument } from "./html";
import { discoverWidgets, loadWidgetDefinition, resolveWidgetPlugins, writeJson } from "./project";
import type { GdanskDevelopmentManifest, WidgetDefinition, WidgetSource } from "./types";
import { createBrowserDescriptorPlugin, createClientPlugin, GDANSK_CLIENT_PATH } from "./virtual";

export async function startDevelopment(options: {
  host: string;
  manifest: string;
  port: number;
  root: string;
}): Promise<never> {
  const widgets = await discoverWidgets(options.root);
  const servers: ViteDevServer[] = [];
  const manifest: GdanskDevelopmentManifest = { root: options.root, widgets: {} };
  try {
    for (const [index, widget] of widgets.entries()) {
      const definition = await loadWidgetDefinition(options.root, widget);
      const port = options.port + index;
      const server = await startWidgetServer(options.root, widget, definition, options.host, port);
      servers.push(server);
      const origin = `http://${options.host}:${port}`;
      manifest.widgets[widget.key] = {
        entry: widget.widgetPath,
        origin,
        page: `${origin}/@gdansk/page`,
      };
    }
    await writeJson(options.manifest, manifest);
    return await new Promise<never>(() => undefined);
  } catch (exc) {
    await Promise.allSettled(servers.map((server) => server.close()));
    throw exc;
  }
}

async function startWidgetServer(
  root: string,
  widget: WidgetSource,
  definition: WidgetDefinition,
  host: string,
  port: number,
): Promise<ViteDevServer> {
  const userPlugins = await resolveWidgetPlugins(definition);
  const controlled: InlineConfig = {
    appType: "custom",
    configFile: false,
    css: createSharedCssModulesConfig(),
    plugins: [
      createGdanskCssModulesPlugin(),
      createClientPlugin(widget),
      createBrowserDescriptorPlugin(),
      createPagePlugin(definition),
      react(),
      ...userPlugins,
    ],
    resolve: {
      alias: [
        { find: /^@gdansk\/widget$/, replacement: "@gdansk/widget/client" },
        { find: "@", replacement: root },
      ],
    },
    root,
    server: { host, port, strictPort: true },
  };
  const server = await createServer(mergeConfig(definition.vite, controlled));
  try {
    await server.listen();
    return server;
  } catch (exc) {
    await server.close();
    throw new Error(`Failed to start isolated dev server for widget ${JSON.stringify(widget.key)}.`, { cause: exc });
  }
}

function createPagePlugin(definition: WidgetDefinition): Plugin {
  return {
    configureServer(server) {
      server.middlewares.use(async (request, response, next) => {
        if (request.url?.split("?", 1)[0] !== "/@gdansk/page") {
          next();
          return;
        }
        try {
          const source = renderDocument({ metadata: definition.metadata, scripts: [GDANSK_CLIENT_PATH] });
          const html = await server.transformIndexHtml(request.url, source);
          response.statusCode = 200;
          response.setHeader("Content-Type", "text/html; charset=utf-8");
          response.end(html);
        } catch (exc) {
          next(exc as Error);
        }
      });
    },
    name: "@gdansk/widget:page",
  };
}
