const Features = {
  Nesting: 1 << 0,
  MediaQueries: 1 << 1,
  LogicalProperties: 1 << 2,
  DirSelector: 1 << 3,
  LightDark: 1 << 4,
};

function transform(options = {}) {
  return {
    code: options.code ?? "",
    warnings: [],
  };
}

function transformStyleAttribute(options = {}) {
  return transform(options);
}

function bundle(options = {}) {
  return transform(options);
}

async function bundleAsync(options = {}) {
  return bundle(options);
}

function browserslistToTargets() {
  return {};
}

function composeVisitors(visitor) {
  return visitor;
}

export {
  Features,
  browserslistToTargets,
  bundle,
  bundleAsync,
  composeVisitors,
  transform,
  transformStyleAttribute,
};
export default {
  Features,
  browserslistToTargets,
  bundle,
  bundleAsync,
  composeVisitors,
  transform,
  transformStyleAttribute,
};
