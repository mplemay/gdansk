if (typeof globalThis.TextEncoder === "undefined") {
  class TextEncoder {
    get encoding() {
      return "utf-8";
    }

    encode(input = "") {
      return Deno.core.encode(String(input));
    }
  }

  globalThis.TextEncoder = TextEncoder;
}

export function runCode(code) {
  return (0, eval)(code);
}

export function setSsrHtml(html) {
  Deno.core.ops.op_gdansk_set_html(html);
}
