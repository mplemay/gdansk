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

async function loadStylesheet() {
  throw new Error(
    "loadStylesheet invoked after Rust @import expansion; extend gdansk_tailwindcss._core if a specifier was missed",
  );
}

/**
 * @param {{
 *   css: string,
 *   moduleId: string,
 *   rootDir: string,
 *   candidates: string[],
 *   tailwindModuleUrl: string,
 * }} input
 */
export default async function tailwindShimTransform(input) {
  const css = input.css;
  const moduleId = input.moduleId;
  const rootDir = input.rootDir;
  const candidates = input.candidates;
  const tailwindModuleUrl = input.tailwindModuleUrl;

  if (typeof css !== "string" || typeof moduleId !== "string" || typeof rootDir !== "string") {
    return { error: "tailwindShimTransform requires css, moduleId, and rootDir strings" };
  }
  if (!Array.isArray(candidates)) {
    return { error: "tailwindShimTransform requires candidates array" };
  }
  if (typeof tailwindModuleUrl !== "string") {
    return { error: "tailwindShimTransform requires tailwindModuleUrl string" };
  }

  try {
    ensureProcess(rootDir);
    const { compile } = await import(tailwindModuleUrl);
    const compiler = await compile(css, {
      base: rootDir,
      from: moduleId,
      loadStylesheet,
    });
    const code = compiler.build(candidates);
    return { code };
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err) };
  }
}
