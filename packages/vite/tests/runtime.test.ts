import { mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import gdansk from "../src";
import { createGdanskRuntime } from "../src/runtime";
import react from "@vitejs/plugin-react";
import { createServer } from "vite";
import { afterEach, describe, expect, it } from "vitest";

const fixtureRoots: string[] = [];

afterEach(async () => {
  await Promise.all(fixtureRoots.splice(0).map((root) => rm(root, { force: true, recursive: true })));
});

describe("@gdansk/vite", () => {
  it("builds widget outputs and serves production SSR", async () => {
    const root = await createFixture({ withLocalPlugin: true });
    const runtime = await createGdanskRuntime({ root, ssrPort: 0 });

    const manifest = await runtime.build();

    expect(Object.keys(manifest.widgets)).toEqual(["hello", "nested/page"]);
    await expect(pathExists(`${root}/.gdansk/hello/client.js`)).resolves.toBe(true);
    await expect(pathExists(`${root}/.gdansk/hello/client.css`)).resolves.toBe(true);
    await expect(pathExists(`${root}/.gdansk/hello/server.js`)).resolves.toBe(true);
    await expect(pathExists(`${root}/.gdansk/nested/page/client.js`)).resolves.toBe(true);
    await expect(pathExists(`${root}/.gdansk/nested/page/server.js`)).resolves.toBe(true);
    await expect(pathExists(`${root}/.gdansk/server.js`)).resolves.toBe(true);

    const metadata = await runtime.startProductionServer();
    const response = await renderWidget(metadata, { widget: "hello" });

    expect(response.body).toContain("Hello SSR");
    expect(response.body).toContain("from plugin");
    expect(response.head.join("")).toContain(`${metadata.ssrOrigin}/.gdansk/hello/client.css`);

    const runtimeMetadata = JSON.parse(await readFile(`${root}/.gdansk/runtime.json`, "utf8")) as {
      assetOrigin: string;
      mode: string;
      widgets: Record<string, { clientPath: string }>;
    };
    expect(runtimeMetadata.assetOrigin).toBe(metadata.ssrOrigin);
    expect(runtimeMetadata.mode).toBe("production");
    expect(runtimeMetadata.widgets.hello.clientPath).toBe("/.gdansk/hello/client.js");

    const assetResponse = await fetch(`${metadata.ssrOrigin}/.gdansk/hello/client.js`);
    expect(assetResponse.status).toBe(200);

    await runtime.close();
  });

  it("starts a dev runtime with a Hono sidecar", async () => {
    const root = await createFixture({ withLocalPlugin: true });
    const runtime = await createGdanskRuntime({ root, ssrPort: 0, vitePort: 0 });
    const metadata = await runtime.startDev();
    const response = await renderWidget(metadata, { component: "hello" });

    expect(response.body).toContain("Hello SSR");
    expect(response.body).toContain("from plugin");
    expect(response.head.join("")).toContain("rel=\"stylesheet\"");
    expect(response.head.join("")).toContain("data-vite-dev-id");

    const runtimeMetadata = JSON.parse(await readFile(`${root}/.gdansk/runtime.json`, "utf8")) as {
      assetOrigin: string;
      viteOrigin: string | null;
      widgets: Record<string, { clientPath: string }>;
    };
    expect(runtimeMetadata.assetOrigin).toMatch(/^http:\/\/127\.0\.0\.1:/);
    expect(runtimeMetadata.viteOrigin).toMatch(/^http:\/\/127\.0\.0\.1:/);
    expect(Object.keys(runtimeMetadata.widgets)).toEqual(["hello", "nested/page"]);
    expect(runtimeMetadata.widgets.hello.clientPath).toBe("/.gdansk-src/hello/client.tsx");

    await runtime.close();
    expect(await pathExists(`${root}/.gdansk/runtime.json`)).toBe(false);
  });

  it("exports a Vite plugin that starts the sidecar during dev", async () => {
    const root = await createFixture({ withLocalPlugin: false });
    const server = await createServer({
      appType: "custom",
      configFile: false,
      plugins: [gdansk({ root, ssrPort: 0 }), react()],
      root,
      server: {
        host: "127.0.0.1",
        port: 0,
      },
    });

    await server.listen();

    const metadata = JSON.parse(await readFile(`${root}/.gdansk/runtime.json`, "utf8")) as {
      ssrEndpoint: string;
      ssrOrigin: string;
    };
    const response = await renderWidget(metadata, { widget: "hello" });

    expect(response.body).toContain("Hello SSR");

    await server.close();
    await waitFor(async () => !(await pathExists(`${root}/.gdansk/runtime.json`)));
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
  await writeFile(
    `${root}/vite.config.ts`,
    ['import react from "@vitejs/plugin-react";', 'import { defineConfig } from "vite";', "", "export default defineConfig({", "  plugins: [react()],", "});", ""].join("\n"),
  );
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
    [
      "export default function App() {",
      '  return <section><h2>Nested widget</h2></section>;',
      "}",
      "",
    ].join("\n"),
  );

  if (options.withLocalPlugin) {
    await mkdir(`${root}/plugins`, { recursive: true });
    await writeFile(
      `${root}/plugins/virtual-message.mjs`,
      [
        "export default {",
        '  name: "virtual-message",',
        "  resolveId(id) {",
        '    return id === "virtual:message" ? id : null;',
        "  },",
        "  load(id) {",
        '    return id === "virtual:message" ? \'export default \"from plugin\";\' : null;',
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

async function waitFor(check: () => Promise<boolean>, attempts: number = 20): Promise<void> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (await check()) {
      return;
    }

    await new Promise((resolveAttempt) => setTimeout(resolveAttempt, 25));
  }

  throw new Error("Condition was not met in time");
}
