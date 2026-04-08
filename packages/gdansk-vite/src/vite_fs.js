import promises from "node:fs/promises";

function realpathSync(path) {
  return Deno.core.ops.op_gdansk_vite_realpath_sync(path);
}

export { promises, realpathSync };
export default { promises, realpathSync };
