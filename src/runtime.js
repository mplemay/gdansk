export function runCode(code) {
  return (0, eval)(code);
}

export function setSsrHtml(html) {
  Deno.core.ops.op_gdansk_set_ssr_html(html);
}
