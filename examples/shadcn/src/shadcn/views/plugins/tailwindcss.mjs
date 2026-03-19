import tailwindcss from "@tailwindcss/vite";
import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);

function canonicalizeExistingFile(filePath) {
  return fs.realpath(filePath);
}

function splitPackageSpecifier(specifier) {
  if (specifier.startsWith("./") || specifier.startsWith("../") || path.isAbsolute(specifier)) {
    return null;
  }

  if (specifier.startsWith("@")) {
    const [, scope, rest] = specifier.match(/^@([^/]+)\/(.+)$/) ?? [];
    if (!scope || !rest) {
      return null;
    }

    const [name, ...subpathParts] = rest.split("/");
    const packageName = `@${scope}/${name}`;
    const subpath = subpathParts.length > 0 ? subpathParts.join("/") : null;
    return { packageName, subpath };
  }

  const [packageName, ...subpathParts] = specifier.split("/");
  const subpath = subpathParts.length > 0 ? subpathParts.join("/") : null;
  return { packageName, subpath };
}

async function findNodeModulesPackageDir(packageName, importerDir, rootDir) {
  let current = importerDir;
  while (true) {
    const candidate = path.join(current, "node_modules", packageName);
    if (await fs.stat(candidate).then((stats) => stats.isDirectory(), () => false)) {
      return candidate;
    }

    if (current === rootDir) {
      break;
    }

    const parent = path.dirname(current);
    if (parent === current) {
      break;
    }

    current = parent;
  }

  return null;
}

async function resolvePackageStyleExport(packageDir, specifier, subpath) {
  const packageJsonPath = path.join(packageDir, "package.json");
  const packageJson = JSON.parse(await fs.readFile(packageJsonPath, "utf8"));
  const exportKey = subpath ? `./${subpath}` : ".";
  const exportEntry = packageJson.exports?.[exportKey];

  if (!exportEntry) {
    throw new Error(`package "${specifier}" does not define exports["${exportKey}"]`);
  }

  const stylePath =
    typeof exportEntry === "string"
      ? exportEntry
      : exportEntry.style ?? packageJson.style ?? null;

  if (!stylePath) {
    throw new Error(`package "${specifier}" does not define a style export for "${exportKey}"`);
  }

  return canonicalizeExistingFile(path.join(packageDir, stylePath));
}

async function resolveCssImportPath(specifier, importerDir, rootDir) {
  if (specifier.startsWith("./") || specifier.startsWith("../")) {
    return canonicalizeExistingFile(path.resolve(importerDir, specifier));
  }

  if (path.isAbsolute(specifier)) {
    return canonicalizeExistingFile(specifier);
  }

  const packageSpec = splitPackageSpecifier(specifier);
  if (!packageSpec) {
    throw new Error(`failed to resolve css import "${specifier}"`);
  }

  const packageDir = await findNodeModulesPackageDir(packageSpec.packageName, importerDir, rootDir);
  if (!packageDir) {
    throw new Error(`failed to resolve css import "${specifier}"`);
  }

  if (packageSpec.subpath) {
    const candidate = path.join(packageDir, packageSpec.subpath);
    try {
      return await canonicalizeExistingFile(candidate);
    } catch {
      // Fall through to package exports.
    }
  }

  return resolvePackageStyleExport(packageDir, specifier, packageSpec.subpath);
}

async function resolveJsImportPath(specifier, importerDir, rootDir) {
  if (specifier.startsWith("./") || specifier.startsWith("../")) {
    return canonicalizeExistingFile(path.resolve(importerDir, specifier));
  }

  if (path.isAbsolute(specifier)) {
    return canonicalizeExistingFile(specifier);
  }

  if (specifier.startsWith("node:")) {
    return specifier;
  }

  const packageSpec = splitPackageSpecifier(specifier);
  if (!packageSpec) {
    throw new Error(`failed to resolve js import "${specifier}"`);
  }

  const packageDir = await findNodeModulesPackageDir(packageSpec.packageName, importerDir, rootDir);
  if (packageDir && packageSpec.subpath) {
    const candidate = path.join(packageDir, packageSpec.subpath);
    try {
      return await canonicalizeExistingFile(candidate);
    } catch {
      // Fall through to Node resolution.
    }
  }

  return require.resolve(specifier, { paths: [importerDir, rootDir] });
}

function createFakeConfig(rootDir) {
  return {
    root: rootDir,
    build: {
      cssMinify: true,
      ssr: false,
    },
    css: {
      devSourcemap: false,
    },
    resolve: {},
    createResolver(options = {}) {
      const isCssResolver =
        options?.extensions?.includes(".css") || options?.mainFields?.includes("style");

      return async (specifier, importer) => {
        const importerDir = importer ? path.dirname(importer) : rootDir;
        if (isCssResolver) {
          return resolveCssImportPath(specifier, importerDir, rootDir);
        }

        return resolveJsImportPath(specifier, importerDir, rootDir);
      };
    },
  };
}

export default function tailwindAdapter(options = {}) {
  return [
    {
      name: "shadcn-tailwindcss",
      async build({ files, pages, readFile, writeFile }) {
        const plugins = tailwindcss(options);
        const scanPlugin = plugins.find((plugin) => plugin.name === "@tailwindcss/vite:scan");
        const buildPlugin = plugins.find((plugin) => plugin.name === "@tailwindcss/vite:generate:build");

        if (!scanPlugin || !buildPlugin) {
          throw new Error("tailwindcss plugin did not expose the expected build hooks");
        }

        await scanPlugin.configResolved(createFakeConfig(pages));

        for (const file of files) {
          const source = await readFile(file);
          const result = await buildPlugin.transform.handler.call(
            {
              environment: null,
              addWatchFile() {},
            },
            source,
            file,
          );

          const code = typeof result === "string" ? result : result?.code;
          if (typeof code !== "string" || code === source) {
            continue;
          }

          await writeFile(file, code);
        }
      },
    },
  ];
}
