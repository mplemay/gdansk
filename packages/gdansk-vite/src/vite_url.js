function fileURLToPath(url) {
  return Deno.core.ops.op_gdansk_vite_file_url_to_path(
    url instanceof URL ? url.href : `${url}`,
  );
}

function pathToFileURL(path) {
  return new URL(Deno.core.ops.op_gdansk_vite_path_to_file_url(path));
}

export { fileURLToPath, pathToFileURL };
export default { fileURLToPath, pathToFileURL };
