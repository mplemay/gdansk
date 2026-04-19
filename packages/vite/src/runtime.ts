import { createServer, mergeConfig } from "vite";

import { buildWidgets, readManifest } from "./build";
import { loadUserViteConfig, prepareProject, resolveOptions } from "./context";
import { resolveViteOrigin } from "./css";
import { createRefreshPlugin } from "./development";
import type {
  GdanskDevRuntimeMetadata,
  GdanskManifest,
  GdanskPluginOptions,
  GdanskPreparedProject,
  GdanskRuntime,
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
    await this.#viteServer?.close();
    this.#viteServer = undefined;
  }

  async refreshWidgets(): Promise<void> {
    const prepared = await this.prepare();
    this.widgets = prepared.widgets;
  }

  async startDev(): Promise<GdanskDevRuntimeMetadata> {
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

    await this.#viteServer.listen();

    const origin = resolveViteOrigin(this.#viteServer);

    return {
      mode: "development",
      viteOrigin: origin,
      widgets: Object.fromEntries(
        prepared.widgets.map((widget) => [widget.key, { clientPath: widget.clientDevEntry }]),
      ),
    };
  }

  async loadOrBuildManifest(): Promise<GdanskManifest> {
    if (this.#manifest) {
      return this.#manifest;
    }

    try {
      this.#manifest = await readManifest(this.manifestPath);
      return this.#manifest;
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
