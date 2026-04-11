import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, posix, resolve } from "node:path";

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
import { createGdanskVirtualModulesPlugin, createResolvedClientModuleId } from "./virtual";

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
        plugins: [createGdanskVirtualModulesPlugin(options, prepared)],
        root: options.root,
      }),
    );
  }

  await build(
    mergeConfig(config, {
      appType: "custom",
      build: createSSRBuildOptions(options, prepared),
      configFile: false,
      plugins: [createGdanskVirtualModulesPlugin(options, prepared)],
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
      ? Object.fromEntries(prepared.widgets.map((widget) => [widget.key, widget.clientModuleId]))
      : { __gdansk_empty__: prepared.ssrEntryId };

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
      input: prepared.ssrEntryId,
      output: {
        chunkFileNames: "chunks/[name]-[hash].js",
        entryFileNames: SERVER_BUNDLE,
      },
    },
    sourcemap: true,
    ssr: true,
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
          const manifestEntry = getClientManifestEntry(widget, clientManifest);
          const fallbackCss = (await pathExists(resolve(options.root, widget.clientCss))) ? [widget.clientCss] : [];
          const css = manifestEntry
            ? await normalizeWidgetCssOutputs(options, widget, manifestEntry.css ?? [])
            : fallbackCss;

          return [
            widget.key,
            {
              client: manifestEntry ? toBuildPath(options, manifestEntry.file) : widget.clientEntry,
              css,
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
  widget: WidgetDefinition,
  manifest: Record<string, ViteManifestEntry>,
): ViteManifestEntry | undefined {
  return Object.values(manifest).find((entry) => entry.file === `${widget.key}/client.js`);
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
  assetInfo?: { names?: string[]; originalFileNames?: string[] },
): string {
  const fileName = assetInfo?.names?.[0] ?? assetInfo?.originalFileNames?.[0] ?? "";

  if (!fileName.endsWith(".css")) {
    return "assets/[name]-[hash][extname]";
  }

  const candidates = [...(assetInfo?.originalFileNames ?? []), ...(assetInfo?.names ?? [])];
  const widget = findWidgetForAsset(widgets, candidates);

  if (!widget) {
    return "assets/[name]-[hash][extname]";
  }

  return toOutputPath(options, widget.clientCss);
}

function findWidgetForAsset(widgets: WidgetDefinition[], assetCandidates: string[]): WidgetDefinition | undefined {
  return widgets.find((widget) => {
    const normalizedModuleId = toPosixPath(widget.clientModuleId);
    const cssName = `assets/${widget.key}`;
    const cssNameWithExt = `${cssName}.css`;

    return assetCandidates.map(toPosixPath).some((normalized) => {
      return (
        normalized === normalizedModuleId ||
        normalized === createResolvedClientModuleId(widget.key) ||
        normalized === cssName ||
        normalized === cssNameWithExt ||
        normalized.endsWith(`/${normalizedModuleId}`) ||
        normalized.endsWith(`/${cssName}`) ||
        normalized.endsWith(`/${cssNameWithExt}`) ||
        normalized.endsWith(`/${widget.key}/client.js`)
      );
    });
  });
}

async function normalizeWidgetCssOutputs(
  options: ResolvedGdanskOptions,
  widget: WidgetDefinition,
  hrefs: string[],
): Promise<string[]> {
  if (hrefs.length !== 1) {
    return hrefs.map((href) => toBuildPath(options, href));
  }

  const [href] = hrefs;
  const target = toOutputPath(options, widget.clientCss);

  if (href === target || href === widget.clientCss) {
    return [toBuildPath(options, target)];
  }

  const sourcePath = resolve(options.outDirPath, href);
  if (!(await pathExists(sourcePath))) {
    return hrefs.map((entry) => toBuildPath(options, entry));
  }

  const targetPath = resolve(options.outDirPath, target);
  const css = await readFile(sourcePath, "utf8");
  const rewrittenCss = rewriteRelativeCssUrls(css, posix.dirname(href), posix.dirname(target));

  await mkdir(dirname(targetPath), { recursive: true });
  await writeFile(targetPath, rewrittenCss);
  await rm(sourcePath, { force: true });

  return [toBuildPath(options, target)];
}

function rewriteRelativeCssUrls(css: string, fromDir: string, toDir: string): string {
  if (fromDir === toDir) {
    return css;
  }

  return css.replace(/url\((['"]?)([^'")]+)\1\)/g, (_match, quote: string, value: string) => {
    if (value.startsWith("/") || value.startsWith("#") || value.startsWith("data:") || /^[a-z]+:/i.test(value)) {
      return `url(${quote}${value}${quote})`;
    }

    const [pathPart, suffix = ""] = splitCssUrl(value);
    const fromPath = posix.join("/", fromDir, pathPart);
    let relativePath = posix.relative(posix.join("/", toDir), fromPath);

    if (!relativePath) {
      relativePath = ".";
    } else if (!relativePath.startsWith(".")) {
      relativePath = `./${relativePath}`;
    }

    return `url(${quote}${relativePath}${suffix}${quote})`;
  });
}

function splitCssUrl(value: string): [string, string] {
  const match = /^([^?#]+)(.*)$/.exec(value);
  return match ? [match[1], match[2]] : [value, ""];
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
