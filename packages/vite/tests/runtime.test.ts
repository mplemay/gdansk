import { mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import {
  build,
  createServer,
  normalizePath,
  type Plugin,
  type PluginOption,
  type UserConfig,
  type ViteDevServer,
} from "vite";
import { afterEach, describe, expect, it, vi } from "vitest";

const viteMocks = vi.hoisted(() => ({
  createServer: vi.fn(),
  createServerImpl: undefined as unknown as (typeof import("vite"))["createServer"],
}));

vi.mock("vite", async (importOriginal) => {
  const actual = await importOriginal<typeof import("vite")>();

  viteMocks.createServerImpl = actual.createServer;
  viteMocks.createServer.mockImplementation(actual.createServer);

  return {
    ...actual,
    createServer: viteMocks.createServer,
  };
});

import gdansk, { gdanskPages } from "../src";
import { resolveOptions } from "../src/context";
import { normalizeRefreshConfig, resolveRefreshPaths } from "../src/development";
import { createGdanskRuntime } from "../src/runtime";

const fixtureRoots: string[] = [];
const RENDER_DEPENDENCY_NAME = "__gdansk_render_cjs_dep__";

type GdanskDevServer = ViteDevServer & {
  __gdansk?: {
    viteOrigin: string;
  };
};

afterEach(async () => {
  viteMocks.createServer.mockReset();
  viteMocks.createServer.mockImplementation(viteMocks.createServerImpl);
  await Promise.all(fixtureRoots.splice(0).map((root) => rm(root, { force: true, recursive: true })));
});

describe("@gdansk/vite", () => {
  it("defaults the frontend runtime to localhost on port 13714", () => {
    const options = resolveOptions({ root: process.cwd() });

    expect(options.buildDirectory).toBe("dist");
    expect(options.host).toBe("127.0.0.1");
    expect(options.port).toBe(13_714);
    expect(options.widgetsDirectory).toBe("widgets");
  });

  it("supports overriding the build directory", () => {
    const options = resolveOptions({ buildDirectory: "public", root: process.cwd() });

    expect(options.buildDirectory).toBe("public");
  });

  it("injects a default @ alias for the frontend package root", async () => {
    const root = await createFixture({ withLocalPlugin: false });
    const config = await resolvePluginConfig(gdansk({}), { root }, "serve");

    expect(config.resolve?.alias).toEqual({
      "@": root,
    });
  });

  it("preserves a user-defined @ alias", async () => {
    const root = await createFixture({ withLocalPlugin: false });
    const config = await resolvePluginConfig(
      gdansk({}),
      {
        resolve: {
          alias: {
            "@": "/custom/root",
          },
        },
        root,
      },
      "serve",
    );

    expect(config.resolve?.alias).toEqual({
      "@": "/custom/root",
    });
  });

  it("appends the default @ alias when alias config uses an array", async () => {
    const root = await createFixture({ withLocalPlugin: false });
    const config = await resolvePluginConfig(
      gdansk({}),
      {
        resolve: {
          alias: [{ find: "~", replacement: "/tmp/shared" }],
        },
        root,
      },
      "serve",
    );

    expect(config.resolve?.alias).toEqual([
      { find: "~", replacement: "/tmp/shared" },
      { find: "@", replacement: root },
    ]);
  });

  it("applies explicit host or port options to the Vite dev server config", async () => {
    const root = await createFixture({ withLocalPlugin: false });
    const config = await resolvePluginConfig(gdansk({ port: 14_000 }), { root }, "serve");

    expect(config.server).toEqual({
      host: "127.0.0.1",
      port: 14_000,
      strictPort: true,
    });
  });

  it("normalizes refresh config for all supported shapes", () => {
    expect(normalizeRefreshConfig(true)).toEqual([
      {
        paths: ["../**/*.py", "../**/*.j2", "../**/*.jinja", "../**/*.jinja2"],
      },
    ]);
    expect(normalizeRefreshConfig("backend/**/*.py")).toEqual([{ paths: ["backend/**/*.py"] }]);
    expect(normalizeRefreshConfig(["a.py", "b.py"])).toEqual([{ paths: ["a.py", "b.py"] }]);
    expect(normalizeRefreshConfig({ paths: "backend/**/*.jinja2" })).toEqual([{ paths: ["backend/**/*.jinja2"] }]);
    expect(normalizeRefreshConfig([{ paths: ["backend/**/*.py"] }, { paths: "templates/**/*.j2" }])).toEqual([
      { paths: ["backend/**/*.py"] },
      { paths: ["templates/**/*.j2"] },
    ]);
  });

  it("resolves refresh globs relative to the frontend package root", async () => {
    const root = await createFixture({ withLocalPlugin: false });

    expect(resolveRefreshPaths(true, root)).toEqual([
      normalizePath(resolve(root, "../**/*.py")),
      normalizePath(resolve(root, "../**/*.j2")),
      normalizePath(resolve(root, "../**/*.jinja")),
      normalizePath(resolve(root, "../**/*.jinja2")),
    ]);
  });

  it("wires full-reload watchers when refresh is enabled", async () => {
    const root = await createFixture({ withLocalPlugin: false });
    const watcher = {
      add: vi.fn(),
      on: vi.fn(),
    };
    const ws = { send: vi.fn() };
    const logger = { info: vi.fn() };
    const refreshPlugin = resolvePluginByName(gdansk({ refresh: true }), "@gdansk/vite:refresh");

    callHook(refreshPlugin.configureServer, {
      config: { logger, root } as unknown as ViteDevServer["config"],
      watcher,
      ws,
    } as unknown as ViteDevServer);

    expect(watcher.add).toHaveBeenCalledWith(resolveRefreshPaths(true, root));
    expect(watcher.on).toHaveBeenCalledTimes(4);

    const changeHandler = watcher.on.mock.calls.find(([event]) => event === "change")?.[1] as
      | ((file: string) => void)
      | undefined;
    const readyHandler = watcher.on.mock.calls.find(([event]) => event === "ready")?.[1] as (() => void) | undefined;

    expect(changeHandler).toBeDefined();
    readyHandler?.();
    changeHandler?.(resolve(root, "../server.py"));

    expect(ws.send).toHaveBeenCalledWith({ path: "*", type: "full-reload" });
  });

  it("passes the refresh plugin into runtime startDev when refresh is enabled", async () => {
    const root = await createFixture({ withLocalPlugin: false });
    const server = {
      close: vi.fn().mockResolvedValue(undefined),
      config: {
        logger: {
          info: vi.fn(),
          warn: vi.fn(),
        },
        root,
        server: {
          host: "127.0.0.1",
          port: 5173,
        },
      },
      httpServer: {
        listening: false,
        once: vi.fn(),
      },
      listen: vi.fn().mockResolvedValue(undefined),
      middlewares: {
        use: vi.fn(),
      },
      resolvedUrls: {
        local: ["http://127.0.0.1:5173/"],
      },
    } as unknown as ViteDevServer;
    viteMocks.createServer.mockResolvedValueOnce(server);
    const runtime = await createGdanskRuntime({ refresh: true, root });

    await runtime.startDev();

    const [config] = viteMocks.createServer.mock.calls[0] ?? [];
    const pluginNames = flattenPluginOptions(config?.plugins ?? []).map((plugin) => plugin.name);

    expect(pluginNames).toContain("@gdansk/vite:refresh");
    expect(pluginNames).toContain("@gdansk/vite:virtual-modules");

    await runtime.close();
  });

  it("warms widget entry modules during dev server setup", async () => {
    const root = await createFixture({ withLocalPlugin: false });
    const logger = { info: vi.fn(), warn: vi.fn() };
    const warmupRequest = vi.fn().mockResolvedValue(undefined);
    const plugin = resolvePluginByName(gdansk({}), "@gdansk/vite");

    await callHook(plugin.configResolved, {
      root,
    } as unknown as Parameters<ConfigResolvedHook>[0]);
    await callHook(plugin.configureServer, {
      config: {
        logger,
        root,
        server: {
          host: "127.0.0.1",
          port: 5173,
        },
      } as unknown as ViteDevServer["config"],
      httpServer: {
        listening: true,
        once: vi.fn(),
      },
      middlewares: {
        use: vi.fn(),
      },
      warmupRequest,
    } as unknown as ViteDevServer);

    await waitFor(async () => warmupRequest.mock.calls.length === 4);

    expect(new Set(warmupRequest.mock.calls.map(([entry]) => entry))).toEqual(
      new Set([
        `${root}/widgets/hello/widget.tsx`,
        `${root}/widgets/nested/page/widget.tsx`,
        "/@gdansk/client/hello.tsx",
        "/@gdansk/client/nested/page.tsx",
      ]),
    );
  });

  it("builds production client artifacts by default", async () => {
    const root = await createFixture({ withLocalPlugin: true });
    const runtime = await createGdanskRuntime({ root, port: 0 });
    expect(runtime.manifestPath).toBe(`${root}/dist/gdansk-manifest.json`);

    const manifest = await runtime.build();

    expect(Object.keys(manifest.widgets)).toEqual(["hello", "nested/page"]);
    await expect(pathExists(`${root}/dist/manifest.json`)).resolves.toBe(true);
    await expect(pathExists(`${root}/dist/gdansk-manifest.json`)).resolves.toBe(true);
    await expect(pathExists(`${root}/dist/hello/client.js`)).resolves.toBe(true);
    await expect(pathExists(`${root}/dist/hello/client.css`)).resolves.toBe(true);
    await expect(pathExists(`${root}/dist/nested/page/client.js`)).resolves.toBe(true);
    await expect(pathExists(`${root}/dist/render.js`)).resolves.toBe(false);
    await expect(pathExists(`${root}/dist/server.js`)).resolves.toBe(false);
    expect(await findMatchingFiles(`${root}/dist/assets`, /\.js$/)).not.toHaveLength(0);
    expect(manifest.widgets.hello.client).toBe("dist/hello/client.js");
    await expect(pathExists(`${root}/dist-src`)).resolves.toBe(false);
    await expect(pathExists(`${root}/__gdansk_virtual__`)).resolves.toBe(false);

    await runtime.close();
  }, 15_000);

  it("builds a manifest when one does not exist yet", async () => {
    const root = await createFixture({ withLocalPlugin: true });
    const runtime = await createGdanskRuntime({ root, port: 0 });
    const manifest = await runtime.loadOrBuildManifest();

    expect(Object.keys(manifest.widgets)).toEqual(["hello", "nested/page"]);
    await expect(pathExists(`${root}/dist/hello/client.js`)).resolves.toBe(true);
    await expect(pathExists(`${root}/dist/render.js`)).resolves.toBe(false);
    await expect(pathExists(`${root}/dist/server.js`)).resolves.toBe(false);
    await runtime.close();
  }, 15_000);

  it("writes manifest paths for static production assets", async () => {
    const root = await createFixture({ withLocalPlugin: true });
    const runtime = await createGdanskRuntime({ root, port: 0 });
    expect(runtime.manifestPath).toBe(`${root}/dist/gdansk-manifest.json`);

    const manifest = await runtime.build();

    expect(Object.keys(manifest.widgets)).toEqual(["hello", "nested/page"]);
    await expect(pathExists(`${root}/dist/manifest.json`)).resolves.toBe(true);
    await expect(pathExists(`${root}/dist/gdansk-manifest.json`)).resolves.toBe(true);
    await expect(pathExists(`${root}/dist/hello/client.js`)).resolves.toBe(true);
    await expect(pathExists(`${root}/dist/hello/client.css`)).resolves.toBe(true);
    await expect(pathExists(`${root}/dist/nested/page/client.js`)).resolves.toBe(true);
    await expect(pathExists(`${root}/dist/render.js`)).resolves.toBe(false);
    await expect(pathExists(`${root}/dist/server.js`)).resolves.toBe(false);
    expect(await findMatchingFiles(`${root}/dist/assets`, /\.js$/)).not.toHaveLength(0);
    expect(manifest.widgets.hello).toEqual({
      client: "dist/hello/client.js",
      css: ["dist/hello/client.css"],
      entry: "hello/widget.tsx",
    });
    expect(manifest.widgets["nested/page"].client).toBe("dist/nested/page/client.js");
    await expect(pathExists(`${root}/dist-src`)).resolves.toBe(false);
    await expect(pathExists(`${root}/__gdansk_virtual__`)).resolves.toBe(false);

    await runtime.close();
  }, 15_000);

  it("copies shared transitive CSS into each widget manifest entry", async () => {
    const root = await createFixture({ withLocalPlugin: false, withSharedCss: true });
    const runtime = await createGdanskRuntime({ root, port: 0 });

    const manifest = await runtime.build();

    expect(manifest.widgets.hello.css).toEqual(["dist/hello/client.css"]);
    expect(manifest.widgets["nested/page"].css).toEqual(["dist/nested/page/client.css"]);
    await expect(pathExists(`${root}/dist/hello/client.css`)).resolves.toBe(true);
    await expect(pathExists(`${root}/dist/nested/page/client.css`)).resolves.toBe(true);
    expect(await findMatchingFiles(`${root}/dist/assets`, /\.css$/)).not.toHaveLength(0);

    await runtime.close();
  }, 15_000);

  it("bundles widget dependencies into the production client output", async () => {
    const root = await createFixture({ withLocalCommonjsDependency: true, withLocalPlugin: false });
    const runtime = await createGdanskRuntime({ root, port: 0 });

    await runtime.build();

    const jsOutputs = await readMatchingFiles(`${root}/dist`, /\.js$/);
    expect(jsOutputs.join("\n")).not.toContain(`"${RENDER_DEPENDENCY_NAME}"`);
    expect(jsOutputs.join("\n")).not.toContain(`'${RENDER_DEPENDENCY_NAME}'`);
    expect(jsOutputs.join("\n")).toContain("from cjs dependency");

    await runtime.close();
  }, 15_000);

  it("starts a dev runtime on a single Vite origin", async () => {
    const root = await createFixture({ withLocalPlugin: true });
    const runtime = await createGdanskRuntime({ root, port: 0 });
    const metadata = await runtime.startDev();

    const viteClientResponse = await fetch(`${metadata.viteOrigin}/@vite/client`);
    expect(viteClientResponse.status).toBe(200);
    expect(Object.keys(metadata.widgets)).toEqual(["hello", "nested/page"]);
    expect(metadata.widgets.hello.clientPath).toBe("/@gdansk/client/hello.tsx");
    await expect(pathExists(`${root}/dist-src`)).resolves.toBe(false);
    await expect(pathExists(`${root}/__gdansk_virtual__`)).resolves.toBe(false);

    await runtime.close();
  }, 15_000);

  it("exports a Vite plugin that exposes the dev Vite origin", async () => {
    const root = await createFixture({ withLocalPlugin: false });
    const server = await createServer({
      appType: "custom",
      configFile: false,
      plugins: [gdansk({ root, port: 0 }), react()],
      root,
      server: {
        host: "127.0.0.1",
        port: 0,
      },
    });

    await server.listen();
    const metadata = (server as GdanskDevServer).__gdansk;

    expect(metadata).toBeDefined();
    expect(metadata?.viteOrigin).toBe(server.resolvedUrls?.local[0]?.replace(/\/$/, ""));
    const viteClientResponse = await fetch(`${metadata!.viteOrigin}/@vite/client`);
    expect(viteClientResponse.status).toBe(200);

    await server.waitForRequestsIdle();
    const httpServer = server.httpServer as
      | (typeof server.httpServer & {
          closeAllConnections?: () => void;
          closeIdleConnections?: () => void;
        })
      | undefined;
    const closeServer = server.close();
    httpServer?.closeIdleConnections?.();
    httpServer?.closeAllConnections?.();
    await closeServer;
    await waitFor(async () => (server as GdanskDevServer).__gdansk === undefined);
  }, 15_000);

  it("configures page-mode builds with a standard Vite manifest", async () => {
    const root = await createPageFixture();
    const config = await resolvePluginConfig(gdanskPages({}), { root }, "build", "@gdansk/vite:pages");

    expect(config.build).toMatchObject({
      copyPublicDir: false,
      emptyOutDir: true,
      manifest: "manifest.json",
      outDir: "dist",
      sourcemap: true,
    });
    expect(config.build?.rollupOptions?.input).toBe(resolve(root, "src/main.tsx"));
    expect(config.resolve?.alias).toEqual({
      "@": root,
    });
  });

  it("builds page-mode production assets with a standard Vite manifest", async () => {
    const root = await createPageFixture();

    await build({
      appType: "custom",
      configFile: false,
      plugins: [gdanskPages({ root }), react()],
      root,
    });

    const manifest = JSON.parse(await readFile(`${root}/dist/manifest.json`, "utf8")) as Record<
      string,
      {
        css?: string[];
        file: string;
        isEntry?: boolean;
      }
    >;

    expect(manifest["src/main.tsx"]?.isEntry).toBe(true);
    expect(manifest["src/main.tsx"]?.file).toMatch(/^assets\/main-.*\.js$/);
    expect(manifest["src/main.tsx"]?.css).toHaveLength(1);
    await expect(pathExists(`${root}/dist/${manifest["src/main.tsx"]?.file}`)).resolves.toBe(true);
    await expect(pathExists(`${root}/dist/${manifest["src/main.tsx"]?.css?.[0]}`)).resolves.toBe(true);
    await expect(pathExists(`${root}/dist/gdansk-manifest.json`)).resolves.toBe(false);
  }, 15_000);

  it("exports a page-mode Vite plugin that exposes the dev Vite origin", async () => {
    const root = await createPageFixture();
    const server = await createServer({
      appType: "custom",
      configFile: false,
      plugins: [gdanskPages({ root, port: 0 }), react()],
      root,
      server: {
        host: "127.0.0.1",
        port: 0,
      },
    });

    await server.listen();
    const metadata = (server as GdanskDevServer).__gdansk;

    expect(metadata).toBeDefined();
    expect(metadata?.viteOrigin).toBe(server.resolvedUrls?.local[0]?.replace(/\/$/, ""));
    const viteClientResponse = await fetch(`${metadata!.viteOrigin}/@vite/client`);
    expect(viteClientResponse.status).toBe(200);

    await server.waitForRequestsIdle();
    const httpServer = server.httpServer as
      | (typeof server.httpServer & {
          closeAllConnections?: () => void;
          closeIdleConnections?: () => void;
        })
      | undefined;
    const closeServer = server.close();
    httpServer?.closeIdleConnections?.();
    httpServer?.closeAllConnections?.();
    await closeServer;
    await waitFor(async () => (server as GdanskDevServer).__gdansk === undefined);
  }, 15_000);
});

async function createFixture(options: {
  withLocalCommonjsDependency?: boolean;
  withLocalPlugin: boolean;
  withSharedCss?: boolean;
}): Promise<string> {
  const root = await mkdtemp(resolve(process.cwd(), ".tmp-vitest-"));
  fixtureRoots.push(root);

  await mkdir(`${root}/widgets/hello`, { recursive: true });
  await mkdir(`${root}/widgets/nested/page`, { recursive: true });
  if (options.withSharedCss) {
    await mkdir(`${root}/widgets/shared`, { recursive: true });
  }
  await writeFile(
    `${root}/package.json`,
    JSON.stringify(
      {
        name: "fixture-views",
        private: true,
        type: "module",
      },
      null,
      2,
    ),
  );
  const viteConfigLines = [
    'import gdansk from "../src/index.ts";',
    'import react from "@vitejs/plugin-react";',
    'import { defineConfig } from "vite";',
  ];

  if (options.withLocalPlugin) {
    viteConfigLines.push('import messagePlugin from "./virtual-message.mjs";');
  }

  viteConfigLines.push(
    "",
    "export default defineConfig({",
    options.withLocalPlugin ? "  plugins: [gdansk(), react(), messagePlugin]," : "  plugins: [gdansk(), react()],",
    "});",
    "",
  );

  await writeFile(`${root}/vite.config.ts`, viteConfigLines.join("\n"));
  if (options.withSharedCss) {
    await writeFile(`${root}/widgets/shared/global.css`, ".shared { color: blue; }\n");
  } else {
    await writeFile(`${root}/widgets/hello/global.css`, ".hello { color: red; }\n");
  }
  if (options.withLocalCommonjsDependency) {
    const dependencyRoot = `${root}/node_modules/${RENDER_DEPENDENCY_NAME}`;
    await mkdir(dependencyRoot, { recursive: true });
    await writeFile(
      `${dependencyRoot}/package.json`,
      JSON.stringify(
        {
          main: "index.js",
          name: RENDER_DEPENDENCY_NAME,
          private: true,
          type: "commonjs",
        },
        null,
        2,
      ),
    );
    await writeFile(`${dependencyRoot}/index.js`, 'module.exports = "from cjs dependency";\n');
  }
  const helloCssImport = options.withSharedCss ? 'import "../shared/global.css";' : 'import "./global.css";';
  const helloClassName = options.withSharedCss ? "shared" : "hello";
  await writeFile(
    `${root}/widgets/hello/widget.tsx`,
    options.withLocalCommonjsDependency
      ? [
          `import message from "${RENDER_DEPENDENCY_NAME}";`,
          helloCssImport,
          "",
          "export default function App() {",
          `  return <main className="${helloClassName}"><h1>Hello production</h1><p>{message}</p></main>;`,
          "}",
          "",
        ].join("\n")
      : options.withLocalPlugin
        ? [
            'import message from "virtual:message";',
            helloCssImport,
            "",
            "export default function App() {",
            `  return <main className="${helloClassName}"><h1>Hello production</h1><p>{message}</p></main>;`,
            "}",
            "",
          ].join("\n")
        : [
            helloCssImport,
            "",
            "export default function App() {",
            `  return <main className="${helloClassName}"><h1>Hello production</h1><p>plain widget</p></main>;`,
            "}",
            "",
          ].join("\n"),
  );
  await writeFile(
    `${root}/widgets/nested/page/widget.tsx`,
    options.withSharedCss
      ? [
          'import "../../shared/global.css";',
          "",
          "export default function App() {",
          '  return <section className="shared"><h2>Nested widget</h2></section>;',
          "}",
          "",
        ].join("\n")
      : ["export default function App() {", "  return <section><h2>Nested widget</h2></section>;", "}", ""].join("\n"),
  );

  if (options.withLocalPlugin) {
    await writeFile(
      `${root}/virtual-message.mjs`,
      [
        "export default {",
        '  name: "virtual-message",',
        "  resolveId(id) {",
        '    return id === "virtual:message" ? id : null;',
        "  },",
        "  load(id) {",
        '    return id === "virtual:message" ? \'export default "from plugin";\' : null;',
        "  },",
        "};",
        "",
      ].join("\n"),
    );
  }

  return root;
}

async function createPageFixture(): Promise<string> {
  const root = await mkdtemp(resolve(process.cwd(), ".tmp-vitest-"));
  fixtureRoots.push(root);

  await mkdir(`${root}/src/Pages`, { recursive: true });
  await writeFile(
    `${root}/package.json`,
    JSON.stringify(
      {
        name: "fixture-pages",
        private: true,
        type: "module",
      },
      null,
      2,
    ),
  );
  await writeFile(`${root}/src/app.css`, ".page { color: red; }\n");
  await writeFile(
    `${root}/src/Pages/Home.tsx`,
    ["export default function Home() {", '  return <main className="page"><h1>Page mode</h1></main>;', "}", ""].join(
      "\n",
    ),
  );
  await writeFile(
    `${root}/src/main.tsx`,
    [
      'import "./app.css";',
      'import { createRoot } from "react-dom/client";',
      'import Home from "./Pages/Home";',
      "",
      'const target = document.createElement("div");',
      "document.body.appendChild(target);",
      "createRoot(target).render(<Home />);",
      "",
    ].join("\n"),
  );

  return root;
}

async function pathExists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

async function findMatchingFiles(root: string, pattern: RegExp): Promise<string[]> {
  if (!(await pathExists(root))) {
    return [];
  }

  const entries = await readdir(root, { withFileTypes: true });
  const matches = await Promise.all(
    entries.map(async (entry) => {
      const path = `${root}/${entry.name}`;

      if (entry.isDirectory()) {
        return findMatchingFiles(path, pattern);
      }

      return pattern.test(entry.name) ? [path] : [];
    }),
  );

  return matches.flat();
}

async function readMatchingFiles(root: string, pattern: RegExp): Promise<string[]> {
  const matches = await findMatchingFiles(root, pattern);
  return Promise.all(matches.map(async (path) => readFile(path, "utf8")));
}

function flattenPluginOptions(option: PluginOption): Plugin[] {
  if (!option) {
    return [];
  }

  if (Array.isArray(option)) {
    return option.flatMap((entry) => flattenPluginOptions(entry));
  }

  return [option as Plugin];
}

function resolvePluginByName(option: PluginOption, name: string): Plugin {
  const plugin = flattenPluginOptions(option).find((entry) => entry.name === name);

  if (!plugin) {
    throw new Error(`Expected plugin "${name}" to be present`);
  }

  return plugin;
}

async function resolvePluginConfig(
  option: PluginOption,
  config: UserConfig,
  command: "build" | "serve",
  name: string = "@gdansk/vite",
): Promise<UserConfig> {
  const plugin = resolvePluginByName(option, name);

  return ((await callHook(plugin.config, config, {
    command,
    mode: command === "build" ? "production" : "development",
  })) ?? {}) as UserConfig;
}

async function waitFor(check: () => Promise<boolean>, attempts: number = 20): Promise<void> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (await check()) {
      return;
    }

    await new Promise((resolveAttempt) => setTimeout(resolveAttempt, 25));
  }

  throw new Error("Condition was not met in time");
}

type HookHandler<T> = T extends { handler: infer Handler extends (...args: any[]) => any }
  ? Handler
  : T extends (...args: any[]) => any
    ? T
    : never;

type ConfigResolvedHook = HookHandler<NonNullable<Plugin["configResolved"]>>;
type HookThis<T> = T extends (this: infer This, ...args: any[]) => any ? This : void;

function resolveHook<T>(hook: T): HookHandler<T> | undefined {
  if (typeof hook === "function") {
    return hook as HookHandler<T>;
  }

  if (hook && typeof hook === "object" && "handler" in hook) {
    return (hook as { handler: HookHandler<T> }).handler;
  }

  return undefined;
}

function callHook<T>(hook: T, ...args: Parameters<HookHandler<T>>): ReturnType<HookHandler<T>> | undefined {
  const handler = resolveHook(hook);

  if (!handler) {
    return undefined;
  }

  return handler.call({} as HookThis<HookHandler<T>>, ...args);
}
