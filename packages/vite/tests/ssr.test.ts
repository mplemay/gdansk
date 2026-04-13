import { describe, expect, it, vi } from "vitest";

import { processSSRRequest } from "../src/ssr";
import { formatSSRError } from "../src/ssr-errors";
import type { GdanskSSRErrorPayload, WidgetDefinition } from "../src/types";

const widgets: WidgetDefinition[] = [
  {
    clientCss: "dist/hello/client.css",
    clientDevEntry: "/@gdansk/client/hello.tsx",
    clientEntry: "dist/hello/client.js",
    clientModuleId: "virtual:gdansk/client/hello",
    entry: "/repo/widgets/hello/widget.tsx",
    key: "hello",
    widgetPath: "hello/widget.tsx",
  },
];

describe("SSR diagnostics", () => {
  it("classifies browser API render errors with widget, hint, and source", async () => {
    const logError = vi.fn();

    const result = await processSSRRequest({
      logError,
      render: () => {
        const error = new Error("document is not defined");
        error.stack = [
          "Error: document is not defined",
          "    at renderWidget (/repo/widgets/hello/widget.tsx:4:7)",
          "    at eval (node:internal/modules/esm/module_job:194:25)",
        ].join("\n");
        throw error;
      },
      requestBody: JSON.stringify({ widget: "hello" }),
      widgets,
    });

    expect(result.status).toBe(500);
    expect(result.payload).toEqual({
      error: {
        hint: expect.stringContaining("useEffect"),
        message: "document is not defined",
        source: "/repo/widgets/hello/widget.tsx:4:7",
        type: "browser_api",
        widget: "hello",
      },
    });
    expect(logError).toHaveBeenCalledWith(
      expect.objectContaining({
        source: "/repo/widgets/hello/widget.tsx:4:7",
        type: "browser_api",
        widget: "hello",
      }),
    );
  });

  it("classifies resolution failures separately from generic render errors", async () => {
    const result = await processSSRRequest({
      render: () => {
        const error = new Error('Cannot find module "@/widgets/hello/widget.tsx"');
        error.stack = "Error: Cannot find module\n    at load (/repo/widgets/hello/widget.tsx:1:1)";
        throw error;
      },
      requestBody: JSON.stringify({ component: "hello" }),
      widgets,
    });

    expect(result.status).toBe(500);
    expect((result.payload as { error: GdanskSSRErrorPayload }).error).toEqual({
      hint: expect.stringContaining("frontend root"),
      message: 'Cannot find module "@/widgets/hello/widget.tsx"',
      source: "/repo/widgets/hello/widget.tsx:1:1",
      type: "component_resolution",
      widget: "hello",
    });
  });

  it("formats SSR diagnostics with relative source context", () => {
    const output = formatSSRError(
      {
        hint: "Move browser-only code into useEffect.",
        message: "document is not defined",
        source: "/repo/widgets/hello/widget.tsx:4:7",
        stack: "Error: document is not defined\n    at renderWidget (/repo/widgets/hello/widget.tsx:4:7)",
        type: "browser_api",
        widget: "hello",
      },
      "/repo",
    );

    expect(output).toContain("GDANSK SSR ERROR");
    expect(output).toContain("hello");
    expect(output).toContain("Source: widgets/hello/widget.tsx:4:7");
    expect(output).toContain("Hint");
  });
});
