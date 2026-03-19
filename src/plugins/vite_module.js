function createIdResolver(config, options = {}) {
  const resolve = config.createResolver(options);

  return async function resolveId(environmentOrId, idOrImporter, importerOrAlias, aliasOnly, ssr) {
    if (typeof environmentOrId === "string" || environmentOrId == null) {
      return resolve(environmentOrId, idOrImporter, importerOrAlias, aliasOnly);
    }

    return resolve(idOrImporter, importerOrAlias, aliasOnly, ssr);
  };
}

export { createIdResolver };
export default { createIdResolver };
