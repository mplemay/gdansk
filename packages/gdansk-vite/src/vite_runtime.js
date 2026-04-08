const BUILD_ENV = {
  command: "build",
  mode: "production",
  ssrBuild: false,
};

const plugins = [];

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

async function normalizePluginExport(exported) {
  if (typeof exported === "function") {
    return normalizePluginExport(await exported());
  }

  if (Array.isArray(exported)) {
    const normalized = [];
    for (const value of exported) {
      normalized.push(...(await normalizePluginExport(value)));
    }
    return normalized;
  }

  if (exported && typeof exported === "object") {
    return [exported];
  }

  throw new Error("Vite plugin modules must export an object, factory, or array");
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
        return Deno.core.ops.op_gdansk_vite_resolve(
          specifier,
          importer ?? null,
          isCssResolver ? "css" : "js",
        );
      };
    },
  };
}

function createTransformContext(watchFiles) {
  return {
    environment: null,
    addWatchFile(file) {
      if (typeof file !== "string" || file.length === 0) {
        return;
      }
      watchFiles.add(Deno.core.ops.op_gdansk_vite_normalize_watch_file(file));
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

globalThis.__gdansk_vite_runtime = {
  async loadPlugins(specs, context) {
    plugins.length = 0;
    const config = createViteConfig(context.pages);

    for (const spec of specs) {
      const mod = await import(spec.moduleSpecifier);
      const exported = await normalizePluginExport(mod.default ?? mod);

      for (const plugin of exported) {
        const name = getPluginName(plugin, spec.moduleSpecifier);
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

    return plugins.length;
  },

  async transformPlugin(index, code, id) {
    const plugin = plugins[index];
    if (!plugin?.transform || !matchesFilter(plugin.transform.filter, id)) {
      return null;
    }

    const watchFiles = new Set();
    try {
      const result = await plugin.transform.handler.call(
        createTransformContext(watchFiles),
        code,
        id,
      );
      return {
        code: extractTransformCode(result),
        watchFiles: [...watchFiles].sort(),
      };
    } catch (error) {
      throw new Error(`[${plugin.name}] transform hook failed: ${getErrorMessage(error)}`);
    }
  },
};
