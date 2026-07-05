import { parseAst, type Plugin } from "vite";

import type { WidgetSource } from "./types";

export const GDANSK_CLIENT_PATH = "/@gdansk/client.tsx";
const RESOLVED_CLIENT_ID = "\0virtual:gdansk/client";
const RESOLVED_DESCRIPTOR_CSS_ID = "\0virtual:gdansk/descriptor-css";

type AstNode = {
  [key: string]: unknown;
  end: number;
  start: number;
  type: string;
};

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

export function createBrowserDescriptorPlugin(): Plugin {
  return {
    enforce: "post",
    name: "@gdansk/widget:browser-descriptor",
    transform(code) {
      if (!code.includes("vitePlugin") || !code.includes("@gdansk/widget")) return null;
      const ast = parseAst(code) as unknown as AstNode;
      const bindings = findVitePluginBindings(ast);
      if (!bindings.size) return null;
      const calls: AstNode[] = [];
      walkAst(ast, (node) => {
        if (node.type !== "CallExpression" || !isAstNode(node.callee) || node.callee.type !== "Identifier") return;
        if (typeof node.callee.name === "string" && bindings.has(node.callee.name)) calls.push(node);
      });
      if (!calls.length) return null;
      let transformed = code;
      for (const call of calls.sort((left, right) => right.start - left.start)) {
        const callee = call.callee as AstNode;
        transformed = `${transformed.slice(0, call.start)}${code.slice(call.start, callee.end)}()${transformed.slice(call.end)}`;
      }
      return { code: transformed, map: null };
    },
  };
}

export function createDescriptorCssPlugin(): Plugin {
  return {
    enforce: "pre",
    load(id) {
      return id === RESOLVED_DESCRIPTOR_CSS_ID ? "export default {};" : null;
    },
    name: "@gdansk/widget:descriptor-css",
    resolveId(source, _importer, options) {
      if (options.ssr && /\.css(?:$|\?)/.test(source)) return RESOLVED_DESCRIPTOR_CSS_ID;
      return null;
    },
  };
}

function findVitePluginBindings(ast: AstNode): Set<string> {
  const bindings = new Set<string>();
  const body = Array.isArray(ast.body) ? ast.body : [];
  for (const statement of body) {
    if (!isAstNode(statement) || statement.type !== "ImportDeclaration" || !isAstNode(statement.source)) continue;
    if (!["@gdansk/widget", "@gdansk/widget/client"].includes(String(statement.source.value))) continue;
    for (const specifier of Array.isArray(statement.specifiers) ? statement.specifiers : []) {
      if (
        isAstNode(specifier) &&
        specifier.type === "ImportSpecifier" &&
        isAstNode(specifier.imported) &&
        specifier.imported.name === "vitePlugin" &&
        isAstNode(specifier.local) &&
        typeof specifier.local.name === "string"
      ) {
        bindings.add(specifier.local.name);
      }
    }
  }
  return bindings;
}

function isAstNode(value: unknown): value is AstNode {
  return typeof value === "object" && value !== null && "type" in value;
}

function walkAst(node: AstNode, visit: (node: AstNode) => void): void {
  visit(node);
  for (const value of Object.values(node)) {
    if (isAstNode(value)) walkAst(value, visit);
    else if (Array.isArray(value)) for (const item of value) if (isAstNode(item)) walkAst(item, visit);
  }
}
