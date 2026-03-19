async function readFile(path, encoding = undefined) {
  return Deno.core.ops.op_gdansk_vite_read_text_file(path, encoding ?? null);
}

export { readFile };
export default { readFile };
