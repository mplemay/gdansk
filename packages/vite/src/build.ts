import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";

import { build, mergeConfig } from "vite";
import type { UserConfig } from "vite";

import { pathExists, toPosixPath } from "./context";
import type {
  GdanskManifest,
  GdanskPreparedProject,
  LoadedProjectConfig,
  ResolvedGdanskOptions,
  WidgetDefinition,
} from "./types";

const CLIENT_MANIFEST_FILE = ".gdansk-client-manifest.json";
const SERVER_BUNDLE = "ssr.js";

type ViteManifestEntry = {
  css?: string[];
  file: string;
};

export function createBuildConfig(options: ResolvedGdanskOptions, prepared: GdanskPreparedProject): UserConfig {
  return {
    appType: "custom",
    builder: {
      sharedPlugins: true,
      async buildApp(builder) {
        if (prepared.widgets.length > 0) {
          await builder.build(builder.environments.client);
        }

        await builder.build(builder.environments.ssr);
        await finalizeBuildOutputs(options, prepared.widgets);
      },
    },
    build: {
      copyPublicDir: false,
      emptyOutDir: true,
      outDir: options.outDir,
      sourcemap: true,
    },
    environments: {
      client: {
        build: createClientBuildOptions(options, prepared),
      },
      ssr: {
        consumer: "server",
        build: createSSRBuildOptions(options, prepared),
      },
    },
  };
}

export async function buildWidgets(
  options: ResolvedGdanskOptions,
  prepared: GdanskPreparedProject,
  config: LoadedProjectConfig = {},
): Promise<GdanskManifest> {
  await rm(options.outDirPath, { force: true, recursive: true });
  await mkdir(options.outDirPath, { recursive: true });

  if (prepared.widgets.length > 0) {
    await build(
      mergeConfig(config, {
        appType: "custom",
        build: createClientBuildOptions(options, prepared),
        configFile: false,
        root: options.root,
      }),
    );
  }

  await build(
    mergeConfig(config, {
      appType: "custom",
      build: createSSRBuildOptions(options, prepared),
      configFile: false,
      root: options.root,
    }),
  );

  return finalizeBuildOutputs(options, prepared.widgets);
}

export async function readManifest(path: string): Promise<GdanskManifest> {
  return JSON.parse(await readFile(path, "utf8")) as GdanskManifest;
}

function createClientBuildOptions(
  options: ResolvedGdanskOptions,
  prepared: GdanskPreparedProject,
): UserConfig["build"] {
  const inputs =
    prepared.widgets.length > 0
      ? Object.fromEntries(prepared.widgets.map((widget) => [widget.key, widget.clientSource]))
      : { __gdansk_empty__: prepared.ssrEntry };

  return {
    copyPublicDir: false,
    cssCodeSplit: true,
    emptyOutDir: true,
    manifest: CLIENT_MANIFEST_FILE,
    outDir: options.outDir,
    rollupOptions: {
      input: inputs,
      output: {
        assetFileNames: (assetInfo: { names?: string[]; originalFileNames?: string[] }) =>
          resolveClientAssetPath(options, prepared.widgets, assetInfo),
        chunkFileNames: "chunks/[name]-[hash].js",
        entryFileNames: ({ name }) => `${name}/client.js`,
      },
    },
    sourcemap: true,
  };
}

function createSSRBuildOptions(options: ResolvedGdanskOptions, prepared: GdanskPreparedProject): UserConfig["build"] {
  return {
    copyPublicDir: false,
    emptyOutDir: false,
    outDir: options.outDir,
    rollupOptions: {
      input: prepared.ssrEntry,
      output: {
        chunkFileNames: "chunks/[name]-[hash].js",
        entryFileNames: SERVER_BUNDLE,
      },
    },
    sourcemap: true,
    ssr: prepared.ssrEntry,
  };
}

async function finalizeBuildOutputs(
  options: ResolvedGdanskOptions,
  widgets: WidgetDefinition[],
): Promise<GdanskManifest> {
  const clientManifest = await readClientManifest(resolve(options.outDirPath, CLIENT_MANIFEST_FILE));

  const manifest: GdanskManifest = {
    outDir: options.outDir,
    root: options.root,
    server: toPosixPath(`${options.outDir}/${SERVER_BUNDLE}`),
    widgets: Object.fromEntries(
      await Promise.all(
        widgets.map(async (widget) => {
          const manifestEntry = getClientManifestEntry(options, widget, clientManifest);
          const fallbackCss = (await pathExists(resolve(options.root, widget.clientCss))) ? [widget.clientCss] : [];

          return [
            widget.key,
            {
              client: manifestEntry ? toBuildPath(options, manifestEntry.file) : widget.clientEntry,
              css: manifestEntry?.css?.map((href) => toBuildPath(options, href)) ?? fallbackCss,
              entry: widget.widgetPath,
            },
          ];
        }),
      ),
    ),
  };

  await rm(resolve(options.outDirPath, CLIENT_MANIFEST_FILE), { force: true });
  await writeJson(resolve(options.outDirPath, "manifest.json"), manifest);
  await writeProductionServer(options);

  return manifest;
}

function getClientManifestEntry(
  options: ResolvedGdanskOptions,
  widget: WidgetDefinition,
  manifest: Record<string, ViteManifestEntry>,
): ViteManifestEntry | undefined {
  const key = toPosixPath(relative(options.root, widget.clientSource));
  return manifest[key];
}

async function readClientManifest(path: string): Promise<Record<string, ViteManifestEntry>> {
  if (!(await pathExists(path))) {
    return {};
  }

  return JSON.parse(await readFile(path, "utf8")) as Record<string, ViteManifestEntry>;
}

function resolveClientAssetPath(
  options: ResolvedGdanskOptions,
  widgets: WidgetDefinition[],
  assetInfo: { names?: string[]; originalFileNames?: string[] },
): string {
  const fileName = assetInfo.names?.[0] ?? assetInfo.originalFileNames?.[0] ?? "";

  if (!fileName.endsWith(".css")) {
    return "assets/[name]-[hash][extname]";
  }

  const originalFileName = assetInfo.originalFileNames?.[0];
  const widget = originalFileName ? findWidgetForAsset(options, widgets, originalFileName) : undefined;

  if (!widget) {
    return "assets/[name]-[hash][extname]";
  }

  return toOutputPath(options, widget.clientCss);
}

function findWidgetForAsset(
  options: ResolvedGdanskOptions,
  widgets: WidgetDefinition[],
  originalFileName: string,
): WidgetDefinition | undefined {
  const normalized = toPosixPath(originalFileName);

  return widgets.find((widget) => {
    const relativeClientSource = toPosixPath(relative(options.root, widget.clientSource));
    return normalized === widget.clientSource || normalized === relativeClientSource;
  });
}

async function writeJson(path: string, value: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, `${JSON.stringify(value, null, 2)}\n`);
}

function toOutputPath(options: ResolvedGdanskOptions, path: string): string {
  const prefix = `${options.outDir}/`;

  if (path.startsWith(prefix)) {
    return path.slice(prefix.length);
  }

  return path;
}

function toBuildPath(options: ResolvedGdanskOptions, path: string): string {
  return path.startsWith(`${options.outDir}/`) ? path : `${options.outDir}/${path.replace(/^\/+/, "")}`;
}

async function writeProductionServer(options: ResolvedGdanskOptions): Promise<void> {
  const path = resolve(options.outDirPath, "server.js");
  const runtimeModuleUrl = new URL("../runtime.js", import.meta.url).href;
  const runtimeOptions = {
    host: options.host,
    port: options.port,
    widgetsRoot: options.widgetsRoot,
  };

  await writeFile(
    path,
    [
      'import { dirname, resolve } from "node:path";',
      'import { fileURLToPath } from "node:url";',
      `import { createGdanskRuntime } from "${runtimeModuleUrl}";`,
      "",
      "const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');",
      `const runtime = await createGdanskRuntime({ ...${JSON.stringify(runtimeOptions)}, root });`,
      "await runtime.startProductionServer();",
      "await new Promise(() => {});",
      "",
    ].join("\n"),
  );
}
