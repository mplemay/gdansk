const builtinModules = ["fs", "fs/promises", "module", "path", "url"];

function createRequire(importer) {
  const importerValue =
    typeof importer === "string"
      ? importer
      : typeof importer?.href === "string"
        ? importer.href
        : String(importer);

  function require(specifier) {
    throw new Error(`require() is not supported in embedded Vite plugins: ${specifier}`);
  }

  require.resolve = (specifier) =>
    Deno.core.ops.op_gdansk_vite_resolve(specifier, importerValue, "js");

  return require;
}

function register() {}

const Module = { createRequire };

export { Module, builtinModules, createRequire, register };
export default { Module, builtinModules, createRequire, register };
