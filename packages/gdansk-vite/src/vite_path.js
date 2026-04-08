function basename(path) {
  return Deno.core.ops.op_gdansk_vite_path_basename(path);
}

function dirname(path) {
  return Deno.core.ops.op_gdansk_vite_path_dirname(path);
}

function extname(path) {
  return Deno.core.ops.op_gdansk_vite_path_extname(path);
}

function relative(from, to) {
  return Deno.core.ops.op_gdansk_vite_path_relative(from, to);
}

function resolve(...paths) {
  return Deno.core.ops.op_gdansk_vite_path_resolve(JSON.stringify(paths));
}

const posix = {
  join(...paths) {
    return Deno.core.ops.op_gdansk_vite_path_posix_join(JSON.stringify(paths));
  },
};

export { basename, dirname, extname, posix, relative, resolve };
export default { basename, dirname, extname, posix, relative, resolve };
