import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

import { cssPathHasModuleTypes } from "./cssModules";

const DEFAULT_CSS_IMPORT_RE = /import\s+\w+\s+from\s+["'](\.[^"']+\.css)["']/g;
const CSS_TYPING_CLASS_RE = /readonly\s+(\w+):/g;

export async function collectTypedCssModuleStyles(entryPath: string, entryScript: string): Promise<string[]> {
  const cssPaths = await findDefaultTypedCssImports(entryPath);
  const styles: string[] = [];

  for (const cssPath of cssPaths) {
    const classNames = await readCssModuleClassNames(cssPath);
    const classMap = extractCssModuleClassMap(entryScript, classNames);
    if (Object.keys(classMap).length === 0) {
      continue;
    }

    const source = await readFile(cssPath, "utf8");
    styles.push(scopeCssWithClassMap(source, classMap));
  }

  return styles;
}

async function findDefaultTypedCssImports(entryPath: string): Promise<string[]> {
  const source = await readFile(entryPath, "utf8");
  const cssPaths: string[] = [];

  for (const match of source.matchAll(DEFAULT_CSS_IMPORT_RE)) {
    const cssPath = resolve(dirname(entryPath), match[1]);
    if (cssPathHasModuleTypes(cssPath)) {
      cssPaths.push(cssPath);
    }
  }

  return cssPaths;
}

async function readCssModuleClassNames(cssPath: string): Promise<string[]> {
  const typings = await readFile(`${cssPath}.d.ts`, "utf8");
  return [...typings.matchAll(CSS_TYPING_CLASS_RE)].map((match) => match[1]);
}

function extractCssModuleClassMap(entryScript: string, classNames: string[]): Record<string, string> {
  const classMap: Record<string, string> = {};

  for (const className of classNames) {
    const match = entryScript.match(new RegExp(`${className}\\s*:\\s*["']([^"']+)["']`));
    if (match) {
      classMap[className] = match[1];
    }
  }

  return classMap;
}

function scopeCssWithClassMap(source: string, classMap: Record<string, string>): string {
  let scoped = source;

  for (const [local, exported] of Object.entries(classMap)) {
    scoped = scoped.replace(new RegExp(`\\.${escapeRegExp(local)}(?=[\\s.{,:>+~])`, "g"), `.${exported}`);
  }

  return scoped;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
