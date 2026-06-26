import { mkdir, mkdtemp, readdir, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import {
  createBuilder,
  createServer,
  normalizePath,
  type Plugin,
  type PluginOption,
  type UserConfig,
  type ViteDevServer,
} from "vite";
import { afterEach, describe, expect, it, vi } from "vitest";
import packageJson from "../package.json";

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

import gdansk, { GDANSK_VERSION } from "../src";
import { pathExists, resolveOptions } from "../src/context";
import { normalizeRefreshConfig, resolveRefreshPaths } from "../src/development";
import { createGdanskRuntime } from "../src/runtime";

const fixtureRoots: string[] = [];
const RENDER_DEPENDENCY_NAME = "__gdansk_render_cjs_dep__";
const UNSCOPED_DEPENDENCY_NAME = "lucide-react";

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

  it("builds inline production widgets by default", async () => {
    const root = await createFixture({ withLocalPlugin: true });
    const runtime = await createGdanskRuntime({ root, port: 0 });
    expect(GDANSK_VERSION).toBe(packageJson.version);

    const manifest = await runtime.build();

    expect(Object.keys(manifest.widgets)).toEqual(["hello", "nested/page"]);
    await expect(pathExists(`${root}/dist`)).resolves.toBe(false);
    expect(manifest.widgets.hello.entry).toBe("hello/widget.tsx");
    expect(manifest.widgets.hello.inline.script).toContain("Hello production");
    expect(manifest.widgets.hello.inline.script).toContain("from plugin");
    expect(manifest.widgets.hello.inline).toEqual({
      script: expect.stringContaining("Hello production"),
      styles: [expect.stringContaining(".hello")],
    });
    expect(manifest.widgets["nested/page"]).toEqual({
      entry: "nested/page/widget.tsx",
      inline: {
        script: expect.stringContaining("Nested widget"),
        styles: [],
      },
    });
    await expect(pathExists(`${root}/dist-src`)).resolves.toBe(false);
    await expect(pathExists(`${root}/__gdansk_virtual__`)).resolves.toBe(false);

    await runtime.close();
  }, 15_000);

  it("builds a manifest when one does not exist yet", async () => {
    const root = await createFixture({ withLocalPlugin: true });
    const runtime = await createGdanskRuntime({ root, port: 0 });
    const manifest = await runtime.loadOrBuildManifest();

    expect(Object.keys(manifest.widgets)).toEqual(["hello", "nested/page"]);
    await expect(pathExists(`${root}/dist`)).resolves.toBe(false);
    expect(manifest.widgets.hello.inline.script).toContain("Hello production");
    await runtime.close();
  }, 15_000);

  it("inlines imported CSS asset URLs", async () => {
    const root = await createFixture({ withCssAsset: true, withLocalPlugin: false });
    const runtime = await createGdanskRuntime({ root, port: 0 });

    const manifest = await runtime.build();

    expect(manifest.widgets.hello.inline.styles).toEqual([expect.stringContaining("data:image/svg+xml")]);
    await expect(pathExists(`${root}/dist`)).resolves.toBe(false);

    await runtime.close();
  }, 15_000);

  it("inlines dynamic imports into the production script", async () => {
    const root = await createFixture({ withDynamicImport: true, withLocalPlugin: false });
    const runtime = await createGdanskRuntime({ root, port: 0 });

    const manifest = await runtime.build();

    expect(manifest.widgets.hello.inline.script).toContain("from dynamic import");
    expect(manifest.widgets.hello.inline.script).not.toContain("dynamic-message");
    expect(await findMatchingFiles(`${root}/dist`, /\.js$/)).toHaveLength(0);

    await runtime.close();
  }, 15_000);

  it("duplicates shared transitive CSS into each widget manifest entry", async () => {
    const root = await createFixture({ withLocalPlugin: false, withSharedCss: true });
    const runtime = await createGdanskRuntime({ root, port: 0 });

    const manifest = await runtime.build();

    expect(manifest.widgets.hello.inline.styles).toEqual([expect.stringContaining(".shared")]);
    expect(manifest.widgets["nested/page"].inline.styles).toEqual([expect.stringContaining(".shared")]);
    expect(manifest.widgets.hello.inline.styles).toEqual(manifest.widgets["nested/page"].inline.styles);
    expect(await findMatchingFiles(`${root}/dist`, /\.css$/)).toHaveLength(0);

    await runtime.close();
  }, 15_000);

  it("bundles widget dependencies into the inline production script", async () => {
    const root = await createFixture({ withLocalCommonjsDependency: true, withLocalPlugin: false });
    const runtime = await createGdanskRuntime({ root, port: 0 });

    const manifest = await runtime.build();

    const script = manifest.widgets.hello.inline.script;
    expect(script).not.toContain(`"${RENDER_DEPENDENCY_NAME}"`);
    expect(script).not.toContain(`'${RENDER_DEPENDENCY_NAME}'`);
    expect(script).toContain("from cjs dependency");

    await runtime.close();
  }, 15_000);

  it("inlines unscoped package dependencies in plugin production builds", async () => {
    const root = await createFixture({ withLocalPlugin: false, withUnscopedDependency: true });

    const builder = await createBuilder({
      appType: "custom",
      builder: {},
      configFile: false,
      plugins: [gdansk({ root }), react()],
      root,
    });
    await builder.buildApp();

    const runtime = await createGdanskRuntime({ root, port: 0 });
    const manifest = await runtime.build();
    const script = manifest.widgets.hello.inline.script;

    expect(script).toContain("from lucide fixture");
    expect(script).not.toMatch(/(?:import|export)\s+[^;]*from\s*["']lucide-react["']/);
    expect(script).not.toMatch(/import\s*\(\s*["']lucide-react["']\s*\)/);
    await expect(pathExists(`${root}/dist`)).resolves.toBe(false);
    await runtime.close();
  }, 15_000);

  it("builds widgets that default-import plain css with co-located css.d.ts typings", async () => {
    const root = await createFixture({ withCssModuleDefaultImport: true, withLocalPlugin: false });
    const runtime = await createGdanskRuntime({ root, port: 0 });

    const manifest = await runtime.build();

    expect(manifest.widgets.hello.inline.script).toContain("Hello production");
    expect(manifest.widgets.hello.inline.styles.length).toBeGreaterThan(0);
    expect(manifest.widgets.hello.inline.styles[0]).toMatch(/color:\s*red/);

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
    const clientResponse = await fetch(`${metadata!.viteOrigin}/@gdansk/client/hello.tsx`);
    expect(clientResponse.status).toBe(200);

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
  withCssAsset?: boolean;
  withCssModuleDefaultImport?: boolean;
  withDynamicImport?: boolean;
  withLocalCommonjsDependency?: boolean;
  withLocalPlugin: boolean;
  withSharedCss?: boolean;
  withUnscopedDependency?: boolean;
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
    await writeFile(
      `${root}/widgets/hello/global.css`,
      options.withCssAsset ? '.hello { background-image: url("./dot.svg"); }\n' : ".hello { color: red; }\n",
    );
  }
  if (options.withCssAsset) {
    await writeFile(`${root}/widgets/hello/dot.svg`, '<svg xmlns="http://www.w3.org/2000/svg"></svg>\n');
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
  if (options.withUnscopedDependency) {
    const dependencyRoot = `${root}/node_modules/${UNSCOPED_DEPENDENCY_NAME}`;
    await mkdir(dependencyRoot, { recursive: true });
    await writeFile(
      `${dependencyRoot}/package.json`,
      JSON.stringify(
        {
          exports: "./index.js",
          name: UNSCOPED_DEPENDENCY_NAME,
          private: true,
          type: "module",
          version: "0.0.0",
        },
        null,
        2,
      ),
    );
    await writeFile(
      `${dependencyRoot}/index.js`,
      [
        'import { createElement } from "react";',
        "",
        "export function CheckIcon() {",
        '  return createElement("span", { "data-lucide": "check" }, "from lucide fixture");',
        "}",
        "",
      ].join("\n"),
    );
  }
  if (options.withDynamicImport) {
    await writeFile(`${root}/widgets/hello/dynamic-message.ts`, 'export const dynamicMessage = "from dynamic import";\n');
  }
  const helloCssImport = options.withCssModuleDefaultImport
    ? 'import styles from "./global.css";'
    : options.withSharedCss
      ? 'import "../shared/global.css";'
      : 'import "./global.css";';
  const helloClassNameAttr = options.withCssModuleDefaultImport
    ? "className={styles.hello}"
    : `className="${options.withSharedCss ? "shared" : "hello"}"`;
  const dynamicImportLines = options.withDynamicImport
    ? ['void import("./dynamic-message").then(({ dynamicMessage }) => console.log(dynamicMessage));']
    : [];
  await writeFile(
    `${root}/widgets/hello/widget.tsx`,
    options.withLocalCommonjsDependency
      ? [
          `import message from "${RENDER_DEPENDENCY_NAME}";`,
          helloCssImport,
          ...dynamicImportLines,
          "",
          "export default function App() {",
          `  return <main ${helloClassNameAttr}><h1>Hello production</h1><p>{message}</p></main>;`,
          "}",
          "",
        ].join("\n")
      : options.withLocalPlugin
        ? [
            'import message from "virtual:message";',
            helloCssImport,
            ...dynamicImportLines,
            "",
            "export default function App() {",
            `  return <main ${helloClassNameAttr}><h1>Hello production</h1><p>{message}</p></main>;`,
            "}",
            "",
          ].join("\n")
        : options.withUnscopedDependency
          ? [
              `import { CheckIcon } from "${UNSCOPED_DEPENDENCY_NAME}";`,
              helloCssImport,
              ...dynamicImportLines,
              "",
              "export default function App() {",
              `  return <main ${helloClassNameAttr}><h1>Hello production</h1><CheckIcon /></main>;`,
              "}",
              "",
            ].join("\n")
          : [
              helloCssImport,
              ...dynamicImportLines,
              "",
              "export default function App() {",
              `  return <main ${helloClassNameAttr}><h1>Hello production</h1><p>plain widget</p></main>;`,
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

  if (options.withCssModuleDefaultImport) {
    await writeFile(
      `${root}/widgets/hello/global.css.d.ts`,
      [
        "declare const styles: {",
        '  readonly hello: string;',
        "};",
        "export default styles;",
        "",
      ].join("\n"),
    );
  }

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
): Promise<UserConfig> {
  const plugin = resolvePluginByName(option, "@gdansk/vite");

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
