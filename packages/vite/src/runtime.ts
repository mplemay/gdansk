import { rm } from "node:fs/promises";
import react from "@vitejs/plugin-react";
import { createServer } from "vite";
import type { InlineConfig } from "vite";
import { buildWidgets, readManifest, writeRuntimeMetadata } from "./build";
import { discoverWidgets, loadProjectPlugins, resolveOptions } from "./context";
import { resolveViteOrigin } from "./css";
import { startSSRSidecar } from "./sidecar";
import type {
  GdanskManifest,
  GdanskPluginOptions,
  GdanskRuntime,
  GdanskRuntimeMetadata,
  ResolvedGdanskOptions,
  WidgetDefinition,
} from "./types";

export async function createGdanskRuntime(options: GdanskPluginOptions = {}): Promise<GdanskRuntime> {
  const resolved = resolveOptions(options);
  const runtime = new GdanskRuntimeImpl(resolved);
  await runtime.refreshWidgets();
  return runtime;
}

class GdanskRuntimeImpl implements GdanskRuntime {
  readonly manifestPath: string;
  readonly options: ResolvedGdanskOptions;
  readonly runtimePath: string;
  widgets: WidgetDefinition[] = [];

  #manifest?: GdanskManifest;
  #sidecar?: Awaited<ReturnType<typeof startSSRSidecar>>;
  #viteServer?: Awaited<ReturnType<typeof createServer>>;

  constructor(options: ResolvedGdanskOptions) {
    this.manifestPath = `${options.outDirPath}/manifest.json`;
    this.options = options;
    this.runtimePath = `${options.outDirPath}/runtime.json`;
  }

  async build(): Promise<GdanskManifest> {
    await this.refreshWidgets();
    const plugins = await loadProjectPlugins(this.options);

    this.#manifest = await buildWidgets(this.options, this.widgets, plugins);

    return this.#manifest;
  }

  async close(): Promise<void> {
    await this.#sidecar?.close();
    this.#sidecar = undefined;

    await this.#viteServer?.close();
    this.#viteServer = undefined;

    await rm(this.runtimePath, { force: true });
  }

  async refreshWidgets(): Promise<void> {
    this.widgets = await discoverWidgets(this.options);
  }

  async startDev(): Promise<GdanskRuntimeMetadata> {
    await this.close();
    await this.refreshWidgets();

    const plugins = await loadProjectPlugins(this.options);

    this.#viteServer = await createServer(this.createViteConfig(plugins));
    await this.#viteServer.listen();

    this.#sidecar = await startSSRSidecar({
      mode: "development",
      options: this.options,
      viteServer: this.#viteServer,
      widgets: this.widgets,
    });

    const metadata: GdanskRuntimeMetadata = {
      mode: "development",
      ssrEndpoint: this.options.ssrEndpoint,
      ssrOrigin: this.#sidecar.origin,
      viteOrigin: resolveViteOrigin(this.#viteServer),
      widgets: this.widgets.map((widget) => widget.key),
    };

    await writeRuntimeMetadata(this.runtimePath, metadata);

    return metadata;
  }

  async startProductionServer(): Promise<GdanskRuntimeMetadata> {
    await this.close();
    await this.refreshWidgets();

    this.#manifest = this.#manifest ?? (await this.loadOrBuildManifest());
    this.#sidecar = await startSSRSidecar({
      manifest: this.#manifest,
      mode: "production",
      options: this.options,
      widgets: this.widgets,
    });

    const metadata: GdanskRuntimeMetadata = {
      mode: "production",
      ssrEndpoint: this.options.ssrEndpoint,
      ssrOrigin: this.#sidecar.origin,
      viteOrigin: null,
      widgets: this.widgets.map((widget) => widget.key),
    };

    await writeRuntimeMetadata(this.runtimePath, metadata);

    return metadata;
  }

  createViteConfig(plugins: Awaited<ReturnType<typeof loadProjectPlugins>>): InlineConfig {
    return {
      appType: "custom",
      configFile: false,
      plugins: [react(), ...plugins],
      root: this.options.root,
      server: {
        host: this.options.host,
        port: this.options.vitePort,
      },
    };
  }

  async loadOrBuildManifest(): Promise<GdanskManifest> {
    try {
      return await readManifest(this.manifestPath);
    } catch {
      return this.build();
    }
  }
}
