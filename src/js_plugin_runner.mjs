import fs from "node:fs/promises";
import path from "node:path";

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
  if (!filter || typeof filter !== "object") {
    return null;
  }

  const include = Array.isArray(filter.include)
    ? filter.include.map(toRegExp).filter(Boolean)
    : [];
  const exclude = Array.isArray(filter.exclude)
    ? filter.exclude.map(toRegExp).filter(Boolean)
    : [];

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

  throw new Error("JS plugin modules must export an object, factory, or array");
}

async function collectCssFiles(root) {
  try {
    const stat = await fs.stat(root);
    if (!stat.isDirectory()) {
      return [];
    }
  } catch {
    return [];
  }

  const files = [];
  const stack = [root];

  while (stack.length > 0) {
    const current = stack.pop();
    const entries = await fs.readdir(current, { withFileTypes: true });
    for (const entry of entries) {
      const filePath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        stack.push(filePath);
        continue;
      }

      if (entry.isFile() && filePath.endsWith(".css")) {
        files.push(filePath);
      }
    }
  }

  files.sort();
  return files;
}

async function runBuild(specs, context) {
  const plugins = [];

  for (const spec of specs) {
    const mod = await import(spec.specifier);
    const exported = await normalizePluginExport(mod.default ?? mod, spec.options);

    for (const plugin of exported) {
      const name = typeof plugin.name === "string" && plugin.name.length > 0 ? plugin.name : spec.specifier;
      plugins.push({
        ...plugin,
        name,
        __filter: normalizeFilter(plugin.filter),
      });
    }
  }

  const cssFiles = await collectCssFiles(context.output);

  for (const plugin of plugins) {
    if (typeof plugin.build !== "function") {
      continue;
    }

    const files = cssFiles.filter((id) => matchesFilter(plugin.__filter, id));
    try {
      await plugin.build({
        pages: context.pages,
        output: context.output,
        files,
        readFile: (filePath) => fs.readFile(filePath, "utf8"),
        writeFile: (filePath, content) => fs.writeFile(filePath, content, "utf8"),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw new Error(`[${plugin.name}] build hook failed: ${message}`);
    }
  }
}

const [, , specsJson, contextJson] = process.argv;
if (!specsJson || !contextJson) {
  throw new Error("JS plugin runner requires specs and context JSON arguments");
}

const specs = JSON.parse(specsJson);
const context = JSON.parse(contextJson);

await runBuild(specs, context);
