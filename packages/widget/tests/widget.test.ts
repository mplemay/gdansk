import { describe, expect, it } from "vitest";
import React from "react";

import { assertWidgetDefinition, render } from "../src/definition";
import { escapeInlineScript, escapeInlineStyle, renderDocument } from "../src/html";
import { renderMetadata } from "../src/metadata";
import { flattenWidgetPlugins } from "../src/project";
import { createBrowserDescriptorPlugin, createClientPlugin, createDescriptorCssPlugin } from "../src/virtual";

describe("@gdansk/widget", () => {
  it("creates a branded widget definition", () => {
    const plugin = { name: "tailwindcss" };
    const definition = render({
      metadata: { description: "Example", title: "Hello" },
      plugins: [plugin],
      widget: React.createElement("main", null, "Hello"),
    });

    expect(assertWidgetDefinition(definition)).toBe(definition);
    expect(definition.plugins[0]).toBe(plugin);
  });

  it("accepts plugin factories and arrays", () => {
    const definition = render({
      plugins: [() => ({ name: "factory" }), [{ name: "nested" }]],
      widget: React.createElement("main"),
    });

    expect(definition.plugins).toHaveLength(2);
  });

  it("flattens plugin options only on the server", async () => {
    const definition = render({
      plugins: [{ name: "resolved-argument" }],
      widget: React.createElement("main"),
    });

    await expect(flattenWidgetPlugins(definition)).resolves.toEqual([{ name: "resolved-argument" }]);
    const client = createClientPlugin({ entry: "/widgets/example/widget.tsx", key: "example", widgetPath: "example/widget.tsx" });
    const source = client.load?.call({} as never, "\0virtual:gdansk/client", {}) as string;
    expect(source).not.toContain("resolved-argument");
  });

  it("replaces descriptor CSS with a non-CSS virtual module", () => {
    const plugin = createDescriptorCssPlugin();
    const resolved = plugin.resolveId?.call({} as never, "./styles.css", "/widget.tsx", { ssr: true }) as string;

    expect(resolved).not.toContain(".css");
    expect(plugin.load?.call({} as never, resolved, {}) as string).toBe("export default {};");
  });

  it("removes server-only plugins and imports from browser widget modules", () => {
    const widget = { entry: "/widgets/example/widget.tsx", key: "example", widgetPath: "example/widget.tsx" };
    const plugin = createBrowserDescriptorPlugin();
    const source = [
      'import tailwindcss from "@tailwindcss/vite";',
      'import { render } from "@gdansk/widget";',
      "",
      "export default function widget() {",
      "  return render({",
      '    plugins: [tailwindcss()],',
      '    widget: <main />',
      "  });",
      "}",
    ].join("\n");
    const transformed = plugin.transform?.call({} as never, source, widget.entry, {}) as { code: string };

    expect(transformed.code).not.toContain("@tailwindcss/vite");
    expect(transformed.code).not.toContain("plugins");
    expect(transformed.code).not.toContain("tailwindcss");
    expect(transformed.code).toContain('widget: <main />');
  });

  it("rejects invalid plugin options", () => {
    expect(() =>
      render({
        plugins: [{ invalid: true } as never],
        widget: React.createElement("main"),
      }),
    ).toThrow("valid Vite plugin options");
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
