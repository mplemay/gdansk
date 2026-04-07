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
  return JSON.parse(Deno.core.ops.op_gdansk_runtime_read_dir(path));
}

function resolvePath(parts) {
  return Deno.core.ops.op_gdansk_runtime_path_resolve(JSON.stringify(parts));
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

      const source = Deno.core.ops.op_gdansk_runtime_read_text_file(path, "utf8");
      for (const token of source.match(CANDIDATE_PATTERN) ?? []) {
        if (isLikelyCandidate(token)) {
          candidates.add(token);
        }
      }
    }
  }

  await walk(rootDir);
  return [...candidates];
}

async function loadStylesheet(specifier, base) {
  const path = Deno.core.ops.op_gdansk_runtime_resolve(specifier, base, "css");
  return {
    base: Deno.core.ops.op_gdansk_runtime_path_dirname(path),
    content: Deno.core.ops.op_gdansk_runtime_read_text_file(path, "utf8"),
    path,
  };
}

function resolveLocalTailwindViteEntry(rootDir) {
  const packageDir = resolvePath([rootDir, "node_modules", "@tailwindcss", "vite"]);
  const packageJsonPath = resolvePath([packageDir, "package.json"]);
  const packageJson = JSON.parse(Deno.core.ops.op_gdansk_runtime_read_text_file(packageJsonPath, "utf8"));
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
  return JSON.parse(Deno.core.ops.op_gdansk_runtime_read_text_file(packageJsonPath, "utf8"));
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
  const entryUrl = Deno.core.ops.op_gdansk_runtime_path_to_file_url(entryPath);
  return await import(entryUrl);
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

async function runFallbackTransform(rootDir, options, source, id) {
  const entryPath = resolveLocalTailwindViteEntry(rootDir);
  const entryUrl = Deno.core.ops.op_gdansk_runtime_path_to_file_url(entryPath);
  const mod = await import(entryUrl);
  const exported = mod.default ?? mod;
  const plugin = typeof exported === "function" ? await exported(options) : exported;
  const handler = getTransformHook(plugin.transform);
  if (!handler) {
    return source;
  }
  const fakeContext = {
    addWatchFile() {},
  };
  const raw = await handler.call(fakeContext, source, id);
  if (typeof raw === "string") {
    return raw;
  }
  if (raw && typeof raw === "object" && typeof raw.code === "string") {
    return raw.code;
  }
  return raw == null ? source : String(raw);
}

/**
 * @param {{ css: string, moduleId: string, rootDir: string, options?: Record<string, unknown> }} input
 */
export default async function tailwindShimTransform(input) {
  const css = input.css;
  const moduleId = input.moduleId;
  const rootDir = input.rootDir;
  const options = input.options ?? {};

  if (typeof css !== "string" || typeof moduleId !== "string" || typeof rootDir !== "string") {
    return { error: "tailwindShimTransform requires css, moduleId, and rootDir strings" };
  }

  let useLocalFallback = false;

  try {
    await importPackage(rootDir, "tailwindcss");
  } catch {
    useLocalFallback = true;
  }

  if (useLocalFallback) {
    try {
      const out = await runFallbackTransform(rootDir, options, css, moduleId);
      return { code: out };
    } catch (err) {
      return { error: err instanceof Error ? err.message : String(err) };
    }
  }

  try {
    ensureProcess(rootDir);
    const { compile } = await importPackage(rootDir, "tailwindcss");
    const compiler = await compile(css, {
      base: rootDir,
      from: moduleId,
      loadStylesheet,
    });
    const candidates = await collectCandidates(rootDir);
    const code = compiler.build(candidates);
    return { code };
  } catch (err) {
    try {
      const out = await runFallbackTransform(rootDir, options, css, moduleId);
      return { code: out };
    } catch (err2) {
      const primary = err instanceof Error ? err.message : String(err);
      const secondary = err2 instanceof Error ? err2.message : String(err2);
      return { error: `${primary}; fallback: ${secondary}` };
    }
  }
}
