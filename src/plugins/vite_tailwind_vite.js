const CONTENT_EXTENSIONS = new Set([
  ".css",
  ".html",
  ".js",
  ".jsx",
  ".md",
  ".mdx",
  ".ts",
  ".tsx",
]);
const IGNORED_DIRECTORIES = new Set([
  ".gdansk",
  ".git",
  "build",
  "dist",
  "node_modules",
]);
const CANDIDATE_PATTERN = /[A-Za-z0-9-_:./[\]%]+/g;

function ensureProcess(rootDir) {
  if (!globalThis.process) {
    globalThis.process = {
      arch: "unknown",
      cwd: () => rootDir,
      env: {},
      platform: "unknown",
      versions: {},
    };
    return;
  }

  globalThis.process.env ??= {};
  globalThis.process.versions ??= {};
  globalThis.process.cwd ??= () => rootDir;
}

function readDir(path) {
  return JSON.parse(Deno.core.ops.op_gdansk_vite_read_dir(path));
}

function resolvePath(parts) {
  return Deno.core.ops.op_gdansk_vite_path_resolve(JSON.stringify(parts));
}

function shouldScanFile(path) {
  for (const extension of CONTENT_EXTENSIONS) {
    if (path.endsWith(extension)) {
      return true;
    }
  }

  return false;
}

function isLikelyCandidate(token) {
  if (token.length === 0 || token.length > 128) {
    return false;
  }

  if (
    token.startsWith(".") ||
    token.startsWith("/") ||
    token.startsWith("@") ||
    token.includes("://") ||
    token.endsWith(".tsx") ||
    token.endsWith(".ts") ||
    token.endsWith(".jsx") ||
    token.endsWith(".js")
  ) {
    return false;
  }

  return /[-:[\]/]/.test(token) || token === "flex" || token === "grid";
}

async function collectCandidates(rootDir) {
  const candidates = new Set();
  const watchFiles = [];

  async function walk(dir) {
    for (const entry of readDir(dir)) {
      const path = resolvePath([dir, entry.name]);
      if (entry.isDirectory) {
        if (IGNORED_DIRECTORIES.has(entry.name)) {
          continue;
        }
        await walk(path);
        continue;
      }
      if (!entry.isFile || !shouldScanFile(path)) {
        continue;
      }

      watchFiles.push(path);
      const source = Deno.core.ops.op_gdansk_vite_read_text_file(path, "utf8");
      for (const token of source.match(CANDIDATE_PATTERN) ?? []) {
        if (isLikelyCandidate(token)) {
          candidates.add(token);
        }
      }
    }
  }

  await walk(rootDir);
  return {
    candidates: [...candidates],
    watchFiles,
  };
}

async function loadStylesheet(specifier, base) {
  const path = Deno.core.ops.op_gdansk_vite_resolve(specifier, base, "css");
  return {
    base: Deno.core.ops.op_gdansk_vite_path_dirname(path),
    content: Deno.core.ops.op_gdansk_vite_read_text_file(path, "utf8"),
    path,
  };
}

function resolveLocalTailwindViteEntry(rootDir) {
  const packageDir = resolvePath([rootDir, "node_modules", "@tailwindcss", "vite"]);
  const packageJsonPath = resolvePath([packageDir, "package.json"]);
  const packageJson = JSON.parse(Deno.core.ops.op_gdansk_vite_read_text_file(packageJsonPath, "utf8"));
  const exported = packageJson.exports?.["."];

  if (typeof exported === "string") {
    return resolvePath([packageDir, exported]);
  }

  if (exported && typeof exported === "object") {
    if (typeof exported.import === "string") {
      return resolvePath([packageDir, exported.import]);
    }
    if (typeof exported.default === "string") {
      return resolvePath([packageDir, exported.default]);
    }
  }

  if (typeof packageJson.module === "string") {
    return resolvePath([packageDir, packageJson.module]);
  }
  if (typeof packageJson.main === "string") {
    return resolvePath([packageDir, packageJson.main]);
  }

  return resolvePath([packageDir, "index.js"]);
}

function readPackageJson(packageDir) {
  const packageJsonPath = resolvePath([packageDir, "package.json"]);
  return JSON.parse(Deno.core.ops.op_gdansk_vite_read_text_file(packageJsonPath, "utf8"));
}

function resolvePackageEntry(rootDir, packageName) {
  const packageDirs = [];
  if (packageName === "tailwindcss") {
    packageDirs.push(resolvePath([rootDir, "node_modules", "tailwindcss"]));
    packageDirs.push(
      resolvePath([rootDir, "node_modules", "@tailwindcss", "vite", "node_modules", "tailwindcss"]),
    );
  } else {
    packageDirs.push(resolvePath([rootDir, "node_modules", ...packageName.split("/")]));
  }

  for (const packageDir of packageDirs) {
    try {
      const packageJson = readPackageJson(packageDir);
      const exported = packageJson.exports?.["."];
      if (typeof exported === "string") {
        return resolvePath([packageDir, exported]);
      }
      if (exported && typeof exported === "object") {
        if (typeof exported.import === "string") {
          return resolvePath([packageDir, exported.import]);
        }
        if (typeof exported.default === "string") {
          return resolvePath([packageDir, exported.default]);
        }
      }
      if (typeof packageJson.module === "string") {
        return resolvePath([packageDir, packageJson.module]);
      }
      if (typeof packageJson.main === "string") {
        return resolvePath([packageDir, packageJson.main]);
      }
      return resolvePath([packageDir, "index.js"]);
    } catch {
      continue;
    }
  }

  throw new Error(`Cannot find module '${packageName}'`);
}

async function importPackage(rootDir, packageName) {
  const entryPath = resolvePackageEntry(rootDir, packageName);
  const entryUrl = Deno.core.ops.op_gdansk_vite_path_to_file_url(entryPath);
  return await import(entryUrl);
}

async function loadFallbackPlugin(rootDir, options) {
  const entryPath = resolveLocalTailwindViteEntry(rootDir);
  const entryUrl = Deno.core.ops.op_gdansk_vite_path_to_file_url(entryPath);
  const mod = await import(entryUrl);
  const exported = mod.default ?? mod;
  return typeof exported === "function" ? await exported(options) : exported;
}

function getTransformHook(transform) {
  if (typeof transform === "function") {
    return transform;
  }
  if (transform && typeof transform === "object" && typeof transform.handler === "function") {
    return transform.handler;
  }
  return null;
}

export default function tailwindVite(options = {}) {
  let rootDir = null;
  let fallbackPlugin = null;
  let useLocalFallback = false;

  async function getFallbackPlugin() {
    fallbackPlugin ??= await loadFallbackPlugin(rootDir, options);
    return fallbackPlugin;
  }

  async function runFallbackTransform(context, source, id) {
    const plugin = await getFallbackPlugin();
    const handler = getTransformHook(plugin.transform);
    if (!handler) {
      return source;
    }
    return await handler.call(context, source, id);
  }

  return {
    name: "@tailwindcss/vite",
    apply: "build",
    async configResolved(config) {
      rootDir = config.root;
      try {
        await importPackage(rootDir, "tailwindcss");
        useLocalFallback = false;
      } catch {
        useLocalFallback = true;
        const plugin = await getFallbackPlugin();
        if (typeof plugin.configResolved === "function") {
          await plugin.configResolved.call(plugin, config);
        }
      }
    },
    transform: {
      filter: {
        id: {
          include: [/\.css(?:\?.*)?$/],
        },
      },
      async handler(source, id) {
        if (!rootDir) {
          return source;
        }

        if (useLocalFallback) {
          return await runFallbackTransform(this, source, id);
        }

        try {
          ensureProcess(rootDir);
          const { compile } = await importPackage(rootDir, "tailwindcss");
          const compiler = await compile(source, {
            base: rootDir,
            from: id,
            loadStylesheet,
          });
          const { candidates, watchFiles } = await collectCandidates(rootDir);
          for (const file of watchFiles) {
            this.addWatchFile(file);
          }
          return compiler.build(candidates);
        } catch {
          useLocalFallback = true;
          return await runFallbackTransform(this, source, id);
        }
      },
    },
  };
}
