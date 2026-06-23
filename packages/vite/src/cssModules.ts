import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

import type { Plugin, UserConfig } from "vite";

const GDANSK_CSS_MODULE_QUERY = "?gdansk-module";
const VIRTUAL_PREFIX = "\0gdansk-css-module:";
const DEFAULT_CSS_IMPORT_RE = /import\s+(\w+)\s+from\s+["'](\.[^"']+\.css)["']/g;
const SOURCE_FILE_RE = /\.(?:[cm]?[jt]sx?)$/;

export function createSharedCssModulesConfig(): UserConfig["css"] {
  return {
    modules: {
      localsConvention: "camelCaseOnly",
    },
  };
}

export function createGdanskCssModulesPlugin(): Plugin {
  return {
    enforce: "pre",
    name: "gdansk-css-modules",
    async resolveId(source, importer, options) {
      if (!importer || !source.includes(GDANSK_CSS_MODULE_QUERY)) {
        return null;
      }

      const cssSource = source.replace(GDANSK_CSS_MODULE_QUERY, "");
      const resolution = await this.resolve(cssSource, importer, { ...options, skipSelf: true });
      const cssPath = resolution?.id.split("?")[0] ?? resolve(dirname(importer.split("?")[0]), cssSource);

      if (!cssPath.endsWith(".css") || cssPath.includes(".module.") || !hasCssModuleTypes(cssPath)) {
        return null;
      }

      return `${VIRTUAL_PREFIX}${toModuleId(cssPath)}`;
    },
    load(id) {
      if (!id.startsWith(VIRTUAL_PREFIX)) {
        return null;
      }

      const cssPath = moduleIdToCssPath(id.slice(VIRTUAL_PREFIX.length));
      if (!cssPath || !hasCssModuleTypes(cssPath)) {
        return null;
      }

      return readFile(cssPath, "utf8");
    },
    transform(code, id) {
      if (!SOURCE_FILE_RE.test(id.split("?")[0])) {
        return null;
      }

      let changed = false;
      const nextCode = code.replace(DEFAULT_CSS_IMPORT_RE, (original, binding, cssImport) => {
        const cssPath = resolve(dirname(id.split("?")[0]), cssImport);
        if (!hasCssModuleTypes(cssPath)) {
          return original;
        }

        changed = true;
        return `import ${binding} from "${cssImport}${GDANSK_CSS_MODULE_QUERY}"`;
      });

      if (!changed) {
        return null;
      }

      return {
        code: nextCode,
        map: null,
      };
    },
  };
}

function hasCssModuleTypes(cssPath: string): boolean {
  return existsSync(`${cssPath}.d.ts`);
}

export function cssPathHasModuleTypes(cssPath: string): boolean {
  return hasCssModuleTypes(cssPath);
}

function toModuleId(cssPath: string): string {
  return cssPath.replace(/\.css(\?.*)?$/, ".module.css$1");
}

function moduleIdToCssPath(moduleId: string): string | null {
  const [pathPart] = splitId(moduleId);
  if (!pathPart.endsWith(".module.css")) {
    return null;
  }

  return pathPart.replace(/\.module\.css$/, ".css");
}

function splitId(resolvedId: string): [string, string | undefined] {
  const queryIndex = resolvedId.indexOf("?");
  if (queryIndex === -1) {
    return [resolvedId, undefined];
  }

  return [resolvedId.slice(0, queryIndex), resolvedId.slice(queryIndex + 1)];
}
