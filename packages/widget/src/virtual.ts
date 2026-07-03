import type { Plugin } from "vite";

import type { WidgetSource } from "./types";

export const GDANSK_CLIENT_PATH = "/@gdansk/client.tsx";
const RESOLVED_CLIENT_ID = "\0virtual:gdansk/client";

export function createClientPlugin(widget: WidgetSource): Plugin {
  return {
    load(id) {
      if (id !== RESOLVED_CLIENT_ID) return null;
      return [
        'import React from "react";',
        'import { createRoot } from "react-dom/client";',
        'import { assertWidgetDefinition } from "@gdansk/widget/client";',
        `import createWidget from ${JSON.stringify(widget.entry)};`,
        "",
        'const root = document.getElementById("root");',
        'if (!root) throw new Error("Gdansk expected a #root element.");',
        `const definition = assertWidgetDefinition(createWidget(), ${JSON.stringify(widget.widgetPath)});`,
        "createRoot(root).render(React.createElement(React.StrictMode, null, definition.widget));",
        "",
      ].join("\n");
    },
    name: "@gdansk/widget:client",
    resolveId(id) {
      return id === GDANSK_CLIENT_PATH ? RESOLVED_CLIENT_ID : null;
    },
  };
}

export function createDescriptorCssPlugin(): Plugin {
  return {
    enforce: "pre",
    load(id, options) {
      if (options?.ssr && /\.css(?:$|\?)/.test(id)) return "export default {};";
      return null;
    },
    name: "@gdansk/widget:descriptor-css",
  };
}
