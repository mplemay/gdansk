import { stat } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { createServer, mergeConfig } from "vite";

import { buildWidgets, readManifest } from "./build";
import { loadUserViteConfig, prepareProject, resolveOptions } from "./context";
import { resolveViteOrigin } from "./css";
import { createRefreshPlugin } from "./development";
import { startGdanskServer } from "./server";
import { installDevSSRMiddleware, importRenderFunction } from "./ssr";
import type {
  GdanskManifest,
  GdanskPluginOptions,
  GdanskPreparedProject,
  GdanskRuntime,
  GdanskRuntimeMetadata,
  GdanskServerHandle,
  ResolvedGdanskOptions,
  WidgetDefinition,
} from "./types";
import { createGdanskVirtualModulesPlugin } from "./virtual";

export async function createGdanskRuntime(options: GdanskPluginOptions = {}): Promise<GdanskRuntime> {
  const resolved = resolveOptions(options);
  const runtime = new GdanskRuntimeImpl(resolved);
  await runtime.refreshWidgets();
  return runtime;
}

class GdanskRuntimeImpl implements GdanskRuntime {
  readonly manifestPath: string;
  readonly options: ResolvedGdanskOptions;
  widgets: WidgetDefinition[] = [];

  #manifest?: GdanskManifest;
  #prepared?: GdanskPreparedProject;
  #server?: GdanskServerHandle;
  #viteServer?: Awaited<ReturnType<typeof createServer>>;

  constructor(options: ResolvedGdanskOptions) {
    this.manifestPath = `${options.buildDirectoryPath}/gdansk-manifest.json`;
    this.options = options;
  }

  async build(): Promise<GdanskManifest> {
    const prepared = await this.prepare();
    const config = await loadUserViteConfig(this.options, "build");

    this.#manifest = await buildWidgets(this.options, prepared, config);

    return this.#manifest;
  }

  async close(): Promise<void> {
    await this.#server?.close();
    this.#server = undefined;

    await this.#viteServer?.close();
    this.#viteServer = undefined;
  }

  async refreshWidgets(): Promise<void> {
    const prepared = await this.prepare();
    this.widgets = prepared.widgets;
  }

  async startDev(): Promise<GdanskRuntimeMetadata> {
    await this.close();
    const prepared = await this.prepare();
    const config = await loadUserViteConfig(this.options, "serve");

    this.#viteServer = await createServer(
      mergeConfig(config, {
        appType: "custom",
        configFile: false,
        plugins: [createGdanskVirtualModulesPlugin(this.options, prepared), createRefreshPlugin(this.options)],
        root: this.options.root,
        server: {
          host: this.options.host,
          port: this.options.port,
          strictPort: true,
        },
      }),
    );

    installDevSSRMiddleware({
      options: this.options,
      server: this.#viteServer,
      ssrEntry: prepared.ssrEntryId,
      widgets: prepared.widgets,
    });

    await this.#viteServer.listen();

    const origin = resolveViteOrigin(this.#viteServer);

    return {
      assetOrigin: origin,
      mode: "development",
      ssrEndpoint: this.options.ssrEndpoint,
      ssrOrigin: origin,
      viteOrigin: origin,
      widgets: Object.fromEntries(
        prepared.widgets.map((widget) => [widget.key, { clientPath: widget.clientDevEntry }]),
      ),
    };
  }

  async startProductionServer(): Promise<GdanskRuntimeMetadata> {
    await this.close();
    const prepared = await this.prepare();

    this.#manifest = this.#manifest ?? (await this.loadOrBuildManifest());
    if (!this.#manifest.server) {
      throw new Error("The production build manifest has no server entry.");
    }

    this.#server = await startGdanskServer({
      manifest: this.#manifest,
      options: this.options,
      render: await loadServerRenderFunction(this.options, this.#manifest.server),
      widgets: prepared.widgets,
    });

    return {
      assetOrigin: this.#server.origin,
      mode: "production",
      ssrEndpoint: this.options.ssrEndpoint,
      ssrOrigin: this.#server.origin,
      viteOrigin: null,
      widgets: Object.fromEntries(
        Object.entries(this.#manifest.widgets).map(([key, widget]) => [key, { clientPath: `/${widget.client}` }]),
      ),
    };
  }

  async loadOrBuildManifest(): Promise<GdanskManifest> {
    try {
      const manifest = await readManifest(this.manifestPath);
      if (!manifest.server) {
        return this.build();
      }

      return manifest;
    } catch {
      return this.build();
    }
  }

  async prepare(): Promise<GdanskPreparedProject> {
    this.#prepared = await prepareProject(this.options);
    this.widgets = this.#prepared.widgets;
    return this.#prepared;
  }
}

async function loadServerRenderFunction(options: ResolvedGdanskOptions, serverEntry: string) {
  const path = resolveServerPath(options, serverEntry);
  const modified = await stat(path);
  return importRenderFunction(`${pathToFileURL(path).href}?t=${modified.mtimeMs}`);
}

function resolveServerPath(options: ResolvedGdanskOptions, serverEntry: string): string {
  return resolve(options.root, serverEntry);
}
