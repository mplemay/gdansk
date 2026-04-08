export default function runInline({ code }) {
  let gdanskHtml = null;
  globalThis.Deno ??= {};
  Deno.core ??= {};
  Deno.core.ops ??= {};
  Deno.core.ops.op_gdansk_set_html = (html) => {
    gdanskHtml = html;
  };

  const result = (0, eval)(code);
  if (gdanskHtml !== null) {
    return gdanskHtml;
  }
  if (result && typeof result.then === "function") {
    return Symbol.for("gdansk.unsupported_promise");
  }

  return gdanskHtml ?? result;
}
