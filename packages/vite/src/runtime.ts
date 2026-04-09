import { createServer, mergeConfig } from "vite";
import { buildWidgets, readManifest } from "./build";
import { loadUserViteConfig, prepareWidgets, resolveOptions } from "./context";
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
  widgets: WidgetDefinition[] = [];

  #manifest?: GdanskManifest;
  #sidecar?: Awaited<ReturnType<typeof startSSRSidecar>>;
  #viteServer?: Awaited<ReturnType<typeof createServer>>;

  constructor(options: ResolvedGdanskOptions) {
    this.manifestPath = `${options.outDirPath}/manifest.json`;
    this.options = options;
  }

  async build(): Promise<GdanskManifest> {
    await this.refreshWidgets();
    const config = await loadUserViteConfig(this.options, "build");

    this.#manifest = await buildWidgets(this.options, this.widgets, config);

    return this.#manifest;
  }

  async close(): Promise<void> {
    await this.#sidecar?.close();
    this.#sidecar = undefined;

    await this.#viteServer?.close();
    this.#viteServer = undefined;
  }

  async refreshWidgets(): Promise<void> {
    this.widgets = await prepareWidgets(this.options);
  }

  async startDev(): Promise<GdanskRuntimeMetadata> {
    await this.close();
    await this.refreshWidgets();

    const config = await loadUserViteConfig(this.options, "serve");

    this.#viteServer = await createServer(
      mergeConfig(config, {
        appType: "custom",
        configFile: false,
        root: this.options.root,
        server: {
          host: this.options.host,
          port: 5173,
          strictPort: true,
        },
      }),
    );
    await this.#viteServer.listen();

    this.#sidecar = await startSSRSidecar({
      mode: "development",
      options: this.options,
      viteServer: this.#viteServer,
      widgets: this.widgets,
    });

    return {
      assetOrigin: resolveViteOrigin(this.#viteServer),
      mode: "development",
      ssrEndpoint: this.options.ssrEndpoint,
      ssrOrigin: this.#sidecar.origin,
      viteOrigin: resolveViteOrigin(this.#viteServer),
      widgets: Object.fromEntries(this.widgets.map((widget) => [widget.key, { clientPath: widget.clientDevEntry }])),
    };
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

    return {
      assetOrigin: this.#sidecar.origin,
      mode: "production",
      ssrEndpoint: this.options.ssrEndpoint,
      ssrOrigin: this.#sidecar.origin,
      viteOrigin: null,
      widgets: Object.fromEntries(
        Object.entries(this.#manifest.widgets).map(([key, widget]) => [key, { clientPath: `/${widget.client}` }]),
      ),
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
