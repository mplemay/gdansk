import fsPromises from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import readline from "node:readline";

const viewsRoot = process.env.GDANSK_TAILWIND_VIEWS_ROOT;
const roots = new Map();

let tailwindModulesPromise = null;

function respond(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

function tailwindPackageError(error) {
  let detail = "unknown error";
  if (error instanceof Error && error.message) {
    detail = error.message;
  }
  return (
    `Tailwind support requires \`tailwindcss\`, \`@tailwindcss/node\`, and ` +
    `\`@tailwindcss/oxide\` in ${viewsRoot}/node_modules. ${detail}`
  );
}

async function loadTailwindModules() {
  if (tailwindModulesPromise !== null) {
    return tailwindModulesPromise;
  }

  tailwindModulesPromise = (async () => {
    if (!viewsRoot) {
      throw new Error("Tailwind worker was started without GDANSK_TAILWIND_VIEWS_ROOT.");
    }

    const resolver = createRequire(path.join(viewsRoot, "__gdansk_tailwind_loader__.cjs"));
    try {
      const tailwindNodePath = resolver.resolve("@tailwindcss/node");
      const oxidePath = resolver.resolve("@tailwindcss/oxide");
      const requireCachePath = resolver.resolve("@tailwindcss/node/require-cache");

      const tailwindNode = await import(pathToFileURL(tailwindNodePath).href);
      const oxide = await import(pathToFileURL(oxidePath).href);
      const requireCache = await import(pathToFileURL(requireCachePath).href);

      return {
        Features: tailwindNode.Features,
        Scanner: oxide.Scanner,
        clearRequireCache: requireCache.clearRequireCache,
        compile: tailwindNode.compile,
      };
    } catch (error) {
      throw new Error(tailwindPackageError(error));
    }
  })();

  return tailwindModulesPromise;
}

class Root {
  constructor(id, base) {
    this.id = id;
    this.base = base;
    this.compiler = undefined;
    this.scanner = undefined;
    this.candidates = new Set();
    this.buildDependencies = new Map();
  }

  get scannedFiles() {
    return this.scanner?.files ?? [];
  }

  async addBuildDependency(filePath) {
    let mtime = null;
    try {
      mtime = (await fsPromises.stat(filePath)).mtimeMs;
    } catch {}
    this.buildDependencies.set(filePath, mtime);
  }

  async requiresBuild() {
    for (const [filePath, mtime] of this.buildDependencies) {
      if (mtime === null) {
        return true;
      }
      try {
        const stat = await fsPromises.stat(filePath);
        if (stat.mtimeMs > mtime) {
          return true;
        }
      } catch {
        return true;
      }
    }
    return false;
  }

  async generate(content) {
    const { Features, Scanner, clearRequireCache, compile } = await loadTailwindModules();
    const inputPath = path.resolve(this.id);
    const watchFiles = new Set();

    const addWatchFile = (filePath) => {
      const resolved = path.resolve(filePath);
      if (resolved === inputPath) {
        return;
      }
      if (/[#?].*\.svg$/.test(resolved)) {
        return;
      }
      watchFiles.add(resolved);
    };

    const inputBase = path.dirname(inputPath);
    if (!this.compiler || !this.scanner || (await this.requiresBuild())) {
      clearRequireCache(Array.from(this.buildDependencies.keys()));
      this.buildDependencies.clear();
      await this.addBuildDependency(inputPath);

      const buildDependencyPromises = [];
      this.compiler = await compile(content, {
        base: inputBase,
        shouldRewriteUrls: true,
        onDependency: (dependencyPath) => {
          addWatchFile(dependencyPath);
          buildDependencyPromises.push(this.addBuildDependency(dependencyPath));
        },
      });
      await Promise.all(buildDependencyPromises);

      const sources = (() => {
        if (this.compiler.root === "none") {
          return [];
        }

        if (this.compiler.root === null) {
          return [{ base: this.base, pattern: "**/*", negated: false }];
        }

        return [{ ...this.compiler.root, negated: false }];
      })().concat(this.compiler.sources);

      this.scanner = new Scanner({ sources });
    } else {
      for (const buildDependency of this.buildDependencies.keys()) {
        addWatchFile(buildDependency);
      }
    }

    if (
      !(
        this.compiler.features &
        (Features.AtApply |
          Features.JsPluginCompat |
          Features.ThemeFunction |
          Features.Utilities)
      )
    ) {
      return false;
    }

    if (this.compiler.features & Features.Utilities) {
      for (const candidate of this.scanner.scan()) {
        this.candidates.add(candidate);
      }
    }

    const watchDirectories = new Set();
    if (this.compiler.features & Features.Utilities) {
      for (const filePath of this.scannedFiles) {
        const resolved = path.resolve(filePath);
        watchFiles.add(resolved);
        const directory = path.dirname(resolved);
        if (directory !== path.resolve(this.base)) {
          watchDirectories.add(directory);
        }
      }
    }

    const code = this.compiler.build([...this.candidates]);

    return {
      code,
      watchDirectories: Array.from(watchDirectories).sort(),
      watchFiles: Array.from(watchFiles).sort(),
    };
  }
}

const rl = readline.createInterface({
  crlfDelay: Infinity,
  input: process.stdin,
});

rl.on("line", async (line) => {
  if (line.trim() === "") {
    return;
  }

  let message;
  try {
    message = JSON.parse(line);
  } catch (error) {
    respond({
      kind: "error",
      error: `Tailwind worker received invalid JSON: ${error instanceof Error ? error.message : String(error)}`,
    });
    return;
  }

  if (message.kind !== "generate") {
    respond({
      kind: "error",
      error: `Tailwind worker does not support request kind ${message.kind}.`,
    });
    return;
  }

  try {
    let root = roots.get(message.id);
    if (!root) {
      root = new Root(message.id, viewsRoot);
      roots.set(message.id, root);
    }

    const result = await root.generate(message.content);
    if (!result) {
      roots.delete(message.id);
      respond({
        kind: "generated",
        id: message.id,
        is_tailwind_root: false,
        watch_files: [],
        watch_directories: [],
      });
      return;
    }

    respond({
      kind: "generated",
      id: message.id,
      is_tailwind_root: true,
      code: result.code,
      watch_files: result.watchFiles,
      watch_directories: result.watchDirectories,
    });
  } catch (error) {
    respond({
      kind: "error",
      error: error instanceof Error ? error.message : String(error),
    });
  }
});

rl.on("close", () => {
  process.exit(0);
});
