import { dirname, relative, resolve, sep } from "node:path";

import type { GdanskPreparedPageProject, ResolvedGdanskPageOptions } from "./types";

export const GDANSK_PAGE_DEV_ENTRY = "/@gdansk/pages/app.tsx";

const PAGE_MODULE_ID = "virtual:gdansk/pages/app";
const RESOLVED_VIRTUAL_PREFIX = "\0";
const SYNTHETIC_ROOT = "__gdansk_virtual__";

export function createPageModuleId(): string {
  return PAGE_MODULE_ID;
}

export function createResolvedPageModuleId(): string {
  return `${RESOLVED_VIRTUAL_PREFIX}${PAGE_MODULE_ID}`;
}

export function resolvePageVirtualModuleId(
  options: ResolvedGdanskPageOptions,
  id: string,
  importer?: string,
): string | null {
  if (id === GDANSK_PAGE_DEV_ENTRY || id === PAGE_MODULE_ID) {
    return createResolvedPageModuleId();
  }

  if (!importer || !id.startsWith(".") || importer !== createResolvedPageModuleId()) {
    return null;
  }

  return resolve(dirname(getSyntheticPagePath(options)), id);
}

export function loadPageVirtualModule(
  options: ResolvedGdanskPageOptions,
  prepared: GdanskPreparedPageProject,
  id: string,
): string | null {
  if (id !== createResolvedPageModuleId()) {
    return null;
  }

  return createPageModuleSource(options, prepared);
}

function createPageModuleSource(options: ResolvedGdanskPageOptions, prepared: GdanskPreparedPageProject): string {
  const syntheticPath = getSyntheticPagePath(options);
  const pageImports = createModuleImports(prepared.pages, syntheticPath, "page");
  const layoutImports = createModuleImports(prepared.layouts, syntheticPath, "layout");
  const pageRegistry = createModuleRegistry(prepared.pages, "page");
  const layoutRegistry = createModuleRegistry(prepared.layouts, "layout");

  return [
    'import React from "react";',
    'import { createInertiaApp } from "@inertiajs/react";',
    'import { createRoot } from "react-dom/client";',
    "",
    ...pageImports,
    ...layoutImports,
    pageRegistry,
    layoutRegistry,
    "const inertiaRootId = document",
    `  .querySelector('script[data-page][type="application/json"]')`,
    '  ?.getAttribute("data-page") ?? "app";',
    "",
    "createInertiaApp({",
    "  id: inertiaRootId,",
    "  progress: false,",
    "  resolve: async (name) => {",
    "    const key = normalizePageKey(name);",
    "    const page = pageModules[key];",
    "",
    "    if (!page) {",
    "      throw new Error(`Unknown page component: ${key}`);",
    "    }",
    "",
    "    return wrapWithLayouts(page, getLayouts(key));",
    "  },",
    "  setup({ App, el, props }) {",
    "    createRoot(el).render(React.createElement(App, props));",
    "  },",
    "});",
    "",
    "function getLayouts(key) {",
    '  const keys = layoutModules["/"] ? ["/"] : [];',
    "",
    '  if (key === "/") {',
    "    return keys.map((layoutKey) => layoutModules[layoutKey]);",
    "  }",
    "",
    "  const parts = key.split('/');",
    "",
    "  for (let index = 0; index < parts.length; index += 1) {",
    "    const layoutKey = parts.slice(0, index + 1).join('/');",
    "",
    "    if (layoutModules[layoutKey]) {",
    "      keys.push(layoutKey);",
    "    }",
    "  }",
    "",
    "  return keys.map((layoutKey) => layoutModules[layoutKey]);",
    "}",
    "",
    "function normalizePageKey(name) {",
    "  const trimmed = String(name).trim();",
    "",
    "  if (!trimmed) {",
    '    throw new Error("Inertia page components must not be empty");',
    "  }",
    "",
    '  if (trimmed === "/") {',
    '    return "/";',
    "  }",
    "",
    "  const normalized = trimmed.replace(/^\\/+|\\/+$/g, '');",
    "",
    "  if (!normalized) {",
    '    return "/";',
    "  }",
    "",
    "  const parts = normalized.split('/');",
    "",
    "  if (parts.some((part) => part === '' || part === '.' || part === '..')) {",
    "    throw new Error(`Invalid page component: ${name}`);",
    "  }",
    "",
    "  return parts.join('/');",
    "}",
    "",
    "function wrapWithLayouts(Page, layouts) {",
    "  let WrappedPage = Page;",
    "",
    "  for (let index = layouts.length - 1; index >= 0; index -= 1) {",
    "    const Layout = layouts[index];",
    "    const PreviousPage = WrappedPage;",
    "",
    "    WrappedPage = function WrappedInertiaPage(props) {",
    "      return React.createElement(Layout, null, React.createElement(PreviousPage, props));",
    "    };",
    "  }",
    "",
    "  return WrappedPage;",
    "}",
    "",
  ].join("\n");
}

function createImportPath(from: string, to: string): string {
  const relativePath = toPosixPath(relative(dirname(from), to));
  return relativePath.startsWith(".") ? relativePath : `./${relativePath}`;
}

function createModuleImports(
  modules: GdanskPreparedPageProject["layouts"] | GdanskPreparedPageProject["pages"],
  syntheticPath: string,
  prefix: "layout" | "page",
): string[] {
  if (modules.length === 0) {
    return [];
  }

  return modules.flatMap((module, index) => [
    `import ${prefix}${index} from ${JSON.stringify(createImportPath(syntheticPath, module.entry))};`,
  ]);
}

function createModuleRegistry(
  modules: GdanskPreparedPageProject["layouts"] | GdanskPreparedPageProject["pages"],
  prefix: "layout" | "page",
): string {
  if (modules.length === 0) {
    return `const ${prefix}Modules = {};\n`;
  }

  return [
    `const ${prefix}Modules = {`,
    ...modules.map((module, index) => `  ${JSON.stringify(module.key)}: ${prefix}${index},`),
    "};",
    "",
  ].join("\n");
}

function getSyntheticPagePath(options: ResolvedGdanskPageOptions): string {
  return resolve(options.root, SYNTHETIC_ROOT, "pages", "app.tsx");
}

function toPosixPath(path: string): string {
  return path.split(sep).join("/");
}
