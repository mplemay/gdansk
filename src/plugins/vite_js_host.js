import path from "node:path";
import fs from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const RESULT_PREFIX = "__GDANSK_VITE_PLUGIN_RESULT__=";
const BUILD_ENV = {
  command: "build",
  mode: "production",
  ssrBuild: false,
};

const require = createRequire(import.meta.url);

function toRegExp(value) {
  if (value instanceof RegExp) {
    return value;
  }

  if (typeof value === "string" && value.length > 0) {
    return new RegExp(value);
  }

  return null;
}

function normalizeFilter(filter) {
  if (!filter) {
    return null;
  }

  const idFilter = filter && typeof filter === "object" && "id" in filter ? filter.id : filter;
  if (!idFilter || typeof idFilter !== "object") {
    return null;
  }

  const include = Array.isArray(idFilter.include) ? idFilter.include.map(toRegExp).filter(Boolean) : [];
  const exclude = Array.isArray(idFilter.exclude) ? idFilter.exclude.map(toRegExp).filter(Boolean) : [];
  if (include.length === 0 && exclude.length === 0) {
    return null;
  }

  return { include, exclude };
}

function matchesFilter(filter, id) {
  if (!filter) {
    return true;
  }

  const matches = (pattern) => {
    pattern.lastIndex = 0;
    return pattern.test(id);
  };

  if (filter.include.length > 0 && !filter.include.some(matches)) {
    return false;
  }

  if (filter.exclude.length > 0 && filter.exclude.some(matches)) {
    return false;
  }

  return true;
}

async function normalizePluginExport(exported, options) {
  if (typeof exported === "function") {
    return normalizePluginExport(await exported(options), options);
  }

  if (Array.isArray(exported)) {
    const plugins = [];
    for (const value of exported) {
      plugins.push(...(await normalizePluginExport(value, options)));
    }
    return plugins;
  }

  if (exported && typeof exported === "object") {
    return [exported];
  }

  throw new Error("Vite plugin modules must export an object, factory, or array");
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

async function canonicalizeExistingFile(filePath) {
  return fs.realpath(filePath);
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

  const stylePath = typeof exportEntry === "string" ? exportEntry : exportEntry.style ?? packageJson.style ?? null;
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

function createViteConfig(rootDir) {
  return {
    root: rootDir,
    mode: BUILD_ENV.mode,
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

function createPackageRequire(rootDir) {
  return createRequire(path.join(rootDir, "__gdansk_vite_plugin_loader__.cjs"));
}

async function importPluginModule(specifier, rootDir) {
  if (specifier.startsWith("file://") || specifier.startsWith("node:")) {
    return import(specifier);
  }

  if (path.isAbsolute(specifier)) {
    return import(pathToFileURL(specifier).href);
  }

  if (specifier.startsWith("./") || specifier.startsWith("../")) {
    return import(pathToFileURL(path.resolve(rootDir, specifier)).href);
  }

  const packageRequire = createPackageRequire(rootDir);
  const resolved = packageRequire.resolve(specifier);
  if (resolved.startsWith("node:")) {
    return import(resolved);
  }

  return import(pathToFileURL(resolved).href);
}

function shouldApply(plugin, config) {
  if (plugin.apply == null) {
    return true;
  }

  if (plugin.apply === "build") {
    return true;
  }

  if (plugin.apply === "serve") {
    return false;
  }

  if (typeof plugin.apply === "function") {
    return Boolean(plugin.apply(config, BUILD_ENV));
  }

  return true;
}

function normalizeTransformHook(transform) {
  if (typeof transform === "function") {
    return {
      filter: normalizeFilter(transform.filter),
      handler: transform,
    };
  }

  if (transform && typeof transform === "object" && typeof transform.handler === "function") {
    return {
      filter: normalizeFilter(transform.filter),
      handler: transform.handler,
    };
  }

  return null;
}

function getPluginName(plugin, fallback) {
  return typeof plugin.name === "string" && plugin.name.length > 0 ? plugin.name : fallback;
}

function getErrorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

async function loadPlugins(specs, context) {
  const config = createViteConfig(context.pages);
  const plugins = [];

  for (const spec of specs) {
    const mod = await importPluginModule(spec.specifier, context.pages);
    const exported = await normalizePluginExport(mod.default ?? mod, spec.options);

    for (const plugin of exported) {
      const name = getPluginName(plugin, spec.specifier);
      if (!shouldApply(plugin, config)) {
        continue;
      }

      if (typeof plugin.configResolved === "function") {
        try {
          await plugin.configResolved.call(plugin, config);
        } catch (error) {
          throw new Error(`[${name}] configResolved hook failed: ${getErrorMessage(error)}`);
        }
      }

      plugins.push({
        name,
        transform: normalizeTransformHook(plugin.transform),
      });
    }
  }

  return plugins;
}

function normalizeWatchFile(file, rootDir) {
  if (typeof file !== "string" || file.length === 0) {
    return null;
  }

  if (file.startsWith("file://")) {
    return fileURLToPath(file);
  }

  if (path.isAbsolute(file)) {
    return path.normalize(file);
  }

  return path.resolve(rootDir, file);
}

function createTransformContext(watchFiles, rootDir) {
  return {
    environment: null,
    addWatchFile(file) {
      const normalized = normalizeWatchFile(file, rootDir);
      if (normalized) {
        watchFiles.add(normalized);
      }
    },
  };
}

function extractTransformCode(result) {
  if (typeof result === "string") {
    return result;
  }

  if (result && typeof result === "object" && typeof result.code === "string") {
    return result.code;
  }

  return null;
}

async function runBuild(payload) {
  const plugins = await loadPlugins(payload.specs, payload.context);
  if (plugins.length === 0 || payload.assets.length === 0) {
    return {
      assets: [],
      watchFiles: [],
    };
  }

  const changedAssets = [];
  const watchFiles = new Set();
  for (const asset of payload.assets) {
    let current = asset.code;
    let changed = false;

    for (const plugin of plugins) {
      if (!plugin.transform || !matchesFilter(plugin.transform.filter, asset.path)) {
        continue;
      }

      try {
        const result = await plugin.transform.handler.call(
          createTransformContext(watchFiles, payload.context.pages),
          current,
          asset.path,
        );
        const nextCode = extractTransformCode(result);
        if (typeof nextCode !== "string" || nextCode === current) {
          continue;
        }

        current = nextCode;
        changed = true;
      } catch (error) {
        throw new Error(`[${plugin.name}] transform hook failed: ${getErrorMessage(error)}`);
      }
    }

    if (changed) {
      changedAssets.push({
        filename: asset.filename,
        code: current,
      });
    }
  }

  return {
    assets: changedAssets,
    watchFiles: [...watchFiles].sort(),
  };
}

async function readPayload() {
  process.stdin.setEncoding("utf8");
  let input = "";
  for await (const chunk of process.stdin) {
    input += chunk;
  }
  if (input.trim().length === 0) {
    throw new Error("Vite plugin host requires a JSON payload on stdin");
  }
  return JSON.parse(input);
}

const payload = await readPayload();
const result = await runBuild(payload);
process.stdout.write(`${RESULT_PREFIX}${JSON.stringify(result)}\n`);
