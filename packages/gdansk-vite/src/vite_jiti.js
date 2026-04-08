function createJiti(importer) {
  const importerValue =
    typeof importer === "string"
      ? importer
      : typeof importer?.href === "string"
        ? importer.href
        : String(importer);

  async function jiti(specifier) {
    return jiti.import(specifier);
  }

  jiti.import = async (specifier) => {
    const resolved = Deno.core.ops.op_gdansk_vite_resolve(specifier, importerValue, "js");
    return await import(resolved);
  };

  return jiti;
}

export { createJiti };
export default { createJiti };
