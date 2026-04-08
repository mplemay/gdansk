export default async function runModule({ sourcePath }) {
  let gdanskHtml = null;
  globalThis.Deno ??= {};
  Deno.core ??= {};
  Deno.core.ops ??= {};
  Deno.core.ops.op_gdansk_set_html = (html) => {
    gdanskHtml = html;
  };

  const mod = await import(sourcePath);
  const result = await mod.default();
  return gdanskHtml ?? result;
}
