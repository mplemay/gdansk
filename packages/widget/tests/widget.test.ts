import { describe, expect, it } from "vitest";
import React from "react";

import { vitePlugin as browserVitePlugin } from "../src/client";
import { assertWidgetDefinition, render, vitePlugin } from "../src/definition";
import { escapeInlineScript, escapeInlineStyle, renderDocument } from "../src/html";
import { renderMetadata } from "../src/metadata";
import { resolveWidgetPlugins } from "../src/project";
import { createBrowserDescriptorPlugin, createClientPlugin, createDescriptorCssPlugin } from "../src/virtual";

describe("@gdansk/widget", () => {
  it("creates a branded widget definition", () => {
    const definition = render({
      metadata: { description: "Example", title: "Hello" },
      plugins: [vitePlugin("@tailwindcss/vite")],
      widget: React.createElement("main", null, "Hello"),
    });

    expect(assertWidgetDefinition(definition)).toBe(definition);
    expect(definition.plugins[0]).toMatchObject({
      __gdanskVitePlugin: true,
      args: [],
      export: "default",
      specifier: "@tailwindcss/vite",
    });
  });

  it("supports named plugin factories and arguments", () => {
    expect(vitePlugin("plugin", { args: [{ enabled: true }], export: "createPlugin" })).toEqual({
      __gdanskVitePlugin: true,
      args: [{ enabled: true }],
      export: "createPlugin",
      specifier: "plugin",
    });
  });

  it("does not retain plugin references in the browser API", () => {
    expect(browserVitePlugin("@tailwindcss/vite", { args: ["secret"], export: "named" })).toEqual({
      __gdanskVitePlugin: true,
      args: [],
      export: "default",
      specifier: "",
    });
  });

  it("resolves and invokes plugin factories only on the server", async () => {
    const definition = render({
      plugins: [
        vitePlugin(
          "data:text/javascript,export function createPlugin(value) { return { name: 'resolved-' + value } }",
          { args: ["argument"], export: "createPlugin" },
        ),
      ],
      widget: React.createElement("main"),
    });

    await expect(resolveWidgetPlugins(definition)).resolves.toEqual([{ name: "resolved-argument" }]);
    const client = createClientPlugin({ entry: "/widgets/example/widget.tsx", key: "example", widgetPath: "example/widget.tsx" });
    const source = client.load?.call({} as never, "\0virtual:gdansk/client", {}) as string;
    expect(source).not.toContain("data:text/javascript");
  });

  it("replaces descriptor CSS with a non-CSS virtual module", () => {
    const plugin = createDescriptorCssPlugin();
    const resolved = plugin.resolveId?.call({} as never, "./styles.css", "/widget.tsx", { ssr: true }) as string;

    expect(resolved).not.toContain(".css");
    expect(plugin.load?.call({} as never, resolved, {}) as string).toBe("export default {};");
  });

  it("removes server-only plugin arguments from browser widget modules", () => {
    const widget = { entry: "/widgets/example/widget.tsx", key: "example", widgetPath: "example/widget.tsx" };
    const plugin = createBrowserDescriptorPlugin();
    const source = 'import { vitePlugin as plugin } from "@gdansk/widget";\nconst value = plugin("secret", { args: [1] });';
    const transformed = plugin.transform?.call({} as never, source, widget.entry, {}) as { code: string };

    expect(transformed.code).toContain("plugin()");
    expect(transformed.code).not.toContain("secret");
    expect(transformed.code).not.toContain("args");
  });

  it("rejects framework-owned Vite options", () => {
    expect(() =>
      render({
        vite: { root: "/tmp" } as never,
        widget: React.createElement("main"),
      }),
    ).toThrow("owns the Vite");
  });

  it("renders and escapes complete HTML", () => {
    const html = renderDocument({
      inlineScript: 'console.log("</script>")',
      metadata: { description: 'A "widget"', title: "Hello" },
      styles: ["main::after{content:'</style>'}"],
    });

    expect(html).toContain("<title>Hello</title>");
    expect(html).toContain('content="A &quot;widget&quot;"');
    expect(html).toContain("<\\/script>");
    expect(html).toContain("<\\/style>");
    expect(escapeInlineScript("</SCRIPT>")).toBe("<\\/script>");
    expect(escapeInlineStyle("</STYLE>")).toBe("<\\/style>");
  });

  it("resolves metadata URLs", () => {
    expect(renderMetadata({ manifest: "app.webmanifest", metadataBase: "https://example.com/base" })).toContain(
      'href="https://example.com/base/app.webmanifest"',
    );
  });
});
