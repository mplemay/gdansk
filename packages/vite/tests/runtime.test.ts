import { mkdir, mkdtemp, rm, stat, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { createServer, type ViteDevServer } from "vite";
import { afterEach, describe, expect, it } from "vitest";

import gdansk from "../src";
import { resolveOptions } from "../src/context";
import { createGdanskRuntime } from "../src/runtime";

const fixtureRoots: string[] = [];

type GdanskDevServer = ViteDevServer & {
  __gdansk?: {
    ssrEndpoint: string;
    ssrOrigin: string;
  };
};

afterEach(async () => {
  await Promise.all(fixtureRoots.splice(0).map((root) => rm(root, { force: true, recursive: true })));
});

describe("@gdansk/vite", () => {
  it("defaults the frontend runtime to localhost on port 13714", () => {
    const options = resolveOptions({ root: process.cwd() });

    expect(options.host).toBe("127.0.0.1");
    expect(options.port).toBe(13_714);
  });

  it("supports overriding the production assets directory", () => {
    const options = resolveOptions({ assets: "public", root: process.cwd() });

    expect(options.outDir).toBe("public");
  });

  it("builds widget outputs and serves production SSR", async () => {
    const root = await createFixture({ withLocalPlugin: true });
    const runtime = await createGdanskRuntime({ root, port: 0 });

    const manifest = await runtime.build();

    expect(Object.keys(manifest.widgets)).toEqual(["hello", "nested/page"]);
    await expect(pathExists(`${root}/assets/hello/client.js`)).resolves.toBe(true);
    await expect(pathExists(`${root}/assets/hello/client.css`)).resolves.toBe(true);
    await expect(pathExists(`${root}/assets/nested/page/client.js`)).resolves.toBe(true);
    await expect(pathExists(`${root}/assets/ssr.js`)).resolves.toBe(true);
    await expect(pathExists(`${root}/assets/server.js`)).resolves.toBe(true);
    expect(manifest.server).toBe("assets/ssr.js");

    const metadata = await runtime.startProductionServer();
    const response = await renderWidget(metadata, { assetBaseUrl: "https://example.com/assets", widget: "hello" });

    expect(response.body).toContain("Hello SSR");
    expect(response.body).toContain("from plugin");
    expect(response.head.join("")).toContain("https://example.com/assets/hello/client.css");

    const health = await fetchHealth(metadata.ssrOrigin);
    expect(health).toEqual({ status: "OK" });
    expect(metadata.ssrEndpoint).toBe("/ssr");

    const assetResponse = await fetch(`${metadata.ssrOrigin}/assets/hello/client.js`);
    expect(assetResponse.status).toBe(200);
    expect(assetResponse.headers.get("access-control-allow-origin")).toBe("*");

    await runtime.close();
  }, 15_000);

  it("starts a dev runtime on a single Vite origin", async () => {
    const root = await createFixture({ withLocalPlugin: true });
    const runtime = await createGdanskRuntime({ root, port: 0 });
    const metadata = await runtime.startDev();
    const response = await renderWidget(metadata, { component: "hello" });

    expect(response.body).toContain("Hello SSR");
    expect(response.body).toContain("from plugin");
    expect(response.head.join("")).toContain('rel="stylesheet"');
    expect(response.head.join("")).toContain("data-vite-dev-id");

    const health = await fetchHealth(metadata.ssrOrigin);
    expect(health).toEqual({ status: "OK" });
    expect(metadata.ssrEndpoint).toBe("/ssr");
    expect(metadata.viteOrigin).toBe(metadata.ssrOrigin);
    expect(metadata.assetOrigin).toBe(metadata.ssrOrigin);
    expect(Object.keys(metadata.widgets)).toEqual(["hello", "nested/page"]);
    expect(metadata.widgets.hello.clientPath).toBe("/dist-src/hello/client.tsx");

    await runtime.close();
  });

  it("exports a Vite plugin that serves health and SSR from the Vite dev server", async () => {
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
    expect(metadata?.ssrEndpoint).toBe("/ssr");
    expect(metadata?.ssrOrigin).toBe(server.resolvedUrls?.local[0]?.replace(/\/$/, ""));
    expect(await fetchHealth(metadata!.ssrOrigin)).toEqual({ status: "OK" });
    const response = await renderWidget(metadata!, { widget: "hello" });

    expect(response.body).toContain("Hello SSR");

    await server.close();
    await waitFor(async () => (server as GdanskDevServer).__gdansk === undefined);
  });
});

async function createFixture(options: { withLocalPlugin: boolean }): Promise<string> {
  const root = await mkdtemp(resolve(process.cwd(), ".tmp-vitest-"));
  fixtureRoots.push(root);

  await mkdir(`${root}/widgets/hello`, { recursive: true });
  await mkdir(`${root}/widgets/nested/page`, { recursive: true });
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
  await writeFile(`${root}/widgets/hello/global.css`, ".hello { color: red; }\n");
  await writeFile(
    `${root}/widgets/hello/widget.tsx`,
    options.withLocalPlugin
      ? [
          'import message from "virtual:message";',
          'import "./global.css";',
          "",
          "export default function App() {",
          '  return <main className="hello"><h1>Hello SSR</h1><p>{message}</p></main>;',
          "}",
          "",
        ].join("\n")
      : [
          'import "./global.css";',
          "",
          "export default function App() {",
          '  return <main className="hello"><h1>Hello SSR</h1><p>plain widget</p></main>;',
          "}",
          "",
        ].join("\n"),
  );
  await writeFile(
    `${root}/widgets/nested/page/widget.tsx`,
    ["export default function App() {", "  return <section><h2>Nested widget</h2></section>;", "}", ""].join("\n"),
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

async function pathExists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

async function renderWidget(
  metadata: { ssrEndpoint: string; ssrOrigin: string },
  body: Record<string, string>,
): Promise<{ body: string; head: string[] }> {
  const response = await fetch(`${metadata.ssrOrigin}${metadata.ssrEndpoint}`, {
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
    method: "POST",
  });

  expect(response.status).toBe(200);
  return (await response.json()) as { body: string; head: string[] };
}

async function fetchHealth(origin: string): Promise<{ status: string }> {
  const response = await fetch(`${origin}/health`);

  expect(response.status).toBe(200);
  return (await response.json()) as { status: string };
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
