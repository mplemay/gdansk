import { parseAst, type Plugin } from "vite";

import type { WidgetSource } from "./types";

export const GDANSK_CLIENT_PATH = "/@gdansk/client.tsx";
const RESOLVED_CLIENT_ID = "\0virtual:gdansk/client";
const RESOLVED_DESCRIPTOR_CSS_ID = "\0virtual:gdansk/descriptor-css";
const GDANSK_WIDGET_SOURCES = new Set(["@gdansk/widget", "@gdansk/widget/client"]);

type AstNode = {
  [key: string]: unknown;
  end: number;
  start: number;
  type: string;
};

type RemovalRange = {
  end: number;
  start: number;
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

export function createWidgetDescriptorPlugin(): Plugin {
  return {
    enforce: "post",
    name: "@gdansk/widget:descriptor",
    transform(code, id) {
      if (!code.includes("render") || !code.includes("@gdansk/widget")) return null;
      const ast = parseAst(code, parserOptions(id), id) as unknown as AstNode;
      const renderBindings = findRenderBindings(ast);
      if (!renderBindings.size) return null;

      const pluginProperties: AstNode[] = [];
      const pluginValues: AstNode[] = [];
      walkAst(ast, (node) => {
        if (node.type !== "CallExpression" || !isAstNode(node.callee) || node.callee.type !== "Identifier") return;
        if (typeof node.callee.name !== "string" || !renderBindings.has(node.callee.name)) return;
        const [argument] = Array.isArray(node.arguments) ? node.arguments : [];
        if (!isAstNode(argument) || argument.type !== "ObjectExpression") return;
        for (const property of Array.isArray(argument.properties) ? argument.properties : []) {
          if (!isAstNode(property) || property.type !== "Property" || !isPluginsPropertyKey(property.key)) continue;
          pluginProperties.push(property);
          if (isAstNode(property.value)) pluginValues.push(property.value);
        }
      });
      if (!pluginProperties.length) return null;

      const pluginIdentifiers = new Set<string>();
      for (const value of pluginValues) collectIdentifiers(value, pluginIdentifiers);

      const removals: RemovalRange[] = pluginProperties.map((property) => propertyRemovalRange(property, code));
      const unusedImports = findUnusedPluginImports(ast, pluginIdentifiers, pluginValues);
      removals.push(...unusedImports);

      if (!removals.length) return null;
      let transformed = code;
      for (const removal of removals.sort((left, right) => right.start - left.start)) {
        transformed = `${transformed.slice(0, removal.start)}${transformed.slice(removal.end)}`;
      }
      return { code: transformed, map: null };
    },
  };
}

export const createBrowserDescriptorPlugin = createWidgetDescriptorPlugin;

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

function parserOptions(id?: string): { lang: "jsx" | "tsx" } | undefined {
  if (id?.endsWith(".tsx")) return { lang: "tsx" };
  if (id?.endsWith(".jsx")) return { lang: "jsx" };
  return undefined;
}

function findRenderBindings(ast: AstNode): Set<string> {
  const bindings = new Set<string>();
  const body = Array.isArray(ast.body) ? ast.body : [];
  for (const statement of body) {
    if (!isAstNode(statement) || statement.type !== "ImportDeclaration" || !isAstNode(statement.source)) continue;
    if (!GDANSK_WIDGET_SOURCES.has(String(statement.source.value))) continue;
    for (const specifier of Array.isArray(statement.specifiers) ? statement.specifiers : []) {
      if (!isAstNode(specifier)) continue;
      if (specifier.type === "ImportSpecifier" && isAstNode(specifier.imported) && specifier.imported.name === "render") {
        if (isAstNode(specifier.local) && typeof specifier.local.name === "string") bindings.add(specifier.local.name);
      }
      if (specifier.type === "ImportDefaultSpecifier" && isAstNode(specifier.local) && specifier.local.name === "render") {
        bindings.add(specifier.local.name);
      }
    }
  }
  return bindings;
}

function isPluginsPropertyKey(key: unknown): boolean {
  if (!isAstNode(key)) return false;
  if (key.type === "Identifier" && key.name === "plugins") return true;
  return key.type === "Literal" && key.value === "plugins";
}

function propertyRemovalRange(property: AstNode, code: string): RemovalRange {
  const body = code.slice(property.start, property.end);
  const leading = body.match(/^\s*,\s*/);
  if (leading) return { end: property.end, start: property.start };
  const trailing = code.slice(property.end).match(/^\s*,\s*/);
  if (trailing) return { end: property.end + trailing[0].length, start: property.start };
  const preceding = code.slice(0, property.start).match(/,\s*$/);
  if (preceding) return { end: property.end, start: property.start - preceding[0].length };
  return { end: property.end, start: property.start };
}

function collectIdentifiers(node: AstNode, identifiers: Set<string>): void {
  walkAst(node, (current) => {
    if (current.type === "Identifier" && typeof current.name === "string") identifiers.add(current.name);
  });
}

function findUnusedPluginImports(ast: AstNode, pluginIdentifiers: Set<string>, pluginValues: AstNode[]): RemovalRange[] {
  const excluded = new Set<AstNode>(pluginValues);
  for (const value of pluginValues) walkAst(value, (node) => excluded.add(node));

  const referenced = new Set<string>();
  walkAst(
    ast,
    (node) => {
      if (excluded.has(node)) return;
      if (node.type === "Identifier" && typeof node.name === "string") referenced.add(node.name);
    },
    (node) => node.type === "ImportDeclaration",
  );

  const unused = new Set([...pluginIdentifiers].filter((name) => !referenced.has(name)));
  if (!unused.size) return [];

  const removals: RemovalRange[] = [];
  const body = Array.isArray(ast.body) ? ast.body : [];
  for (const statement of body) {
    if (!isAstNode(statement) || statement.type !== "ImportDeclaration") continue;
    const specifiers = Array.isArray(statement.specifiers) ? statement.specifiers : [];
    const locals = specifiers
      .map((specifier) => (isAstNode(specifier) && isAstNode(specifier.local) ? specifier.local.name : null))
      .filter((name): name is string => typeof name === "string");
    if (!locals.length || !locals.every((name) => unused.has(name))) continue;
    removals.push({ end: statement.end, start: statement.start });
  }
  return removals;
}

function isAstNode(value: unknown): value is AstNode {
  return typeof value === "object" && value !== null && "type" in value;
}

function walkAst(node: AstNode, visit: (node: AstNode) => void, skip?: (node: AstNode) => boolean): void {
  if (skip?.(node)) return;
  visit(node);
  for (const value of Object.values(node)) {
    if (isAstNode(value)) walkAst(value, visit, skip);
    else if (Array.isArray(value)) for (const item of value) if (isAstNode(item)) walkAst(item, visit, skip);
  }
}
