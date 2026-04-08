async function readFile(path, encoding = undefined) {
  return Deno.core.ops.op_gdansk_vite_read_text_file(path, encoding ?? null);
}

async function stat(path) {
  const result = JSON.parse(Deno.core.ops.op_gdansk_vite_stat(path));
  return {
    mtimeMs: result.mtimeMs,
    isDirectory() {
      return result.isDirectory;
    },
    isFile() {
      return result.isFile;
    },
  };
}

export { readFile, stat };
export default { readFile, stat };
