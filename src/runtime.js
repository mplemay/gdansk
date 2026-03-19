function getScheduleMicrotask(global) {
  if (typeof global.queueMicrotask === "function") {
    return global.queueMicrotask.bind(global);
  }
  return (callback) => Promise.resolve().then(callback);
}

function installMessageChannelShim(global, scheduleMicrotask) {
  if (typeof global.MessagePort !== "undefined") {
    return;
  }

  class MessagePort {
    constructor() {
      this._target = null;
      this._listeners = new Set();
      this.onmessage = null;
      this._closed = false;
    }

    postMessage(data) {
      if (this._closed || !this._target || this._target._closed) {
        return;
      }

      const target = this._target;
      scheduleMicrotask(() => {
        if (target._closed) {
          return;
        }

        const event = { data };
        if (typeof target.onmessage === "function") {
          target.onmessage(event);
        }
        for (const listener of target._listeners) {
          listener(event);
        }
      });
    }

    addEventListener(type, callback) {
      if (type !== "message" || typeof callback !== "function") {
        return;
      }
      this._listeners.add(callback);
    }

    removeEventListener(type, callback) {
      if (type !== "message" || typeof callback !== "function") {
        return;
      }
      this._listeners.delete(callback);
    }

    start() {}

    close() {
      this._closed = true;
    }
  }

  class MessageChannel {
    constructor() {
      this.port1 = new MessagePort();
      this.port2 = new MessagePort();
      this.port1._target = this.port2;
      this.port2._target = this.port1;
    }
  }

  global.MessagePort = MessagePort;
  global.MessageChannel = MessageChannel;
}

function installTextEncoderShim(global) {
  if (typeof global.TextEncoder !== "undefined") {
    return;
  }

  class TextEncoder {
    get encoding() {
      return "utf-8";
    }

    encode(input = "") {
      return Deno.core.encode(String(input));
    }
  }

  global.TextEncoder = TextEncoder;
}

function installRuntimeShims(global) {
  const scheduleMicrotask = getScheduleMicrotask(global);
  installMessageChannelShim(global, scheduleMicrotask);
  installTextEncoderShim(global);
}

installRuntimeShims(globalThis);

export function runCode(code) {
  return (0, eval)(code);
}

export function setSsrHtml(html) {
  Deno.core.ops.op_gdansk_set_html(html);
}

function toRegExp(value) {
  if (value instanceof RegExp) {
    return value;
  }

  if (typeof value === "string" && value.length > 0) {
    return new RegExp(value);
  }

  return null;
}

function normalizeFilter(filter) {
  if (!filter || typeof filter !== "object") {
    return null;
  }

  const include = Array.isArray(filter.include)
    ? filter.include.map(toRegExp).filter(Boolean)
    : [];
  const exclude = Array.isArray(filter.exclude)
    ? filter.exclude.map(toRegExp).filter(Boolean)
    : [];

  return { include, exclude };
}

function matchesFilter(filter, id) {
  if (!filter) {
    return true;
  }

  const matches = (pattern) => {
    pattern.lastIndex = 0;
    return pattern.test(id);
  };

  if (filter.include.length > 0 && !filter.include.some(matches)) {
    return false;
  }

  if (filter.exclude.length > 0 && filter.exclude.some(matches)) {
    return false;
  }

  return true;
}

async function normalizePluginExport(exported, options) {
  if (typeof exported === "function") {
    return normalizePluginExport(await exported(options), options);
  }

  if (Array.isArray(exported)) {
    const plugins = [];
    for (const value of exported) {
      plugins.push(...(await normalizePluginExport(value, options)));
    }
    return plugins;
  }

  if (exported && typeof exported === "object") {
    return [exported];
  }

  throw new Error("JS plugin modules must export an object, factory, or array");
}

export async function loadPlugins(specs) {
  const plugins = [];

  for (const spec of specs) {
    const mod = await import(spec.specifier);
    const exported = await normalizePluginExport(mod.default ?? mod, spec.options);

    for (const plugin of exported) {
      const name = typeof plugin.name === "string" && plugin.name.length > 0 ? plugin.name : spec.specifier;
      plugins.push({
        ...plugin,
        name,
        __filter: normalizeFilter(plugin.filter),
      });
    }
  }

  globalThis.__gdansk_js_plugins = plugins;
}

export async function runBuild({ pages, output }) {
  const plugins = globalThis.__gdansk_js_plugins ?? [];
  const cssFiles = Deno.core.ops.op_gdansk_scan_css_files(output);

  for (const plugin of plugins) {
    if (typeof plugin.build !== "function") {
      continue;
    }

    const files = cssFiles.filter((id) => matchesFilter(plugin.__filter, id));
    try {
      await plugin.build({
        pages,
        output,
        files,
        readFile: (path) => Deno.core.ops.op_gdansk_read_text_file(path),
        writeFile: (path, content) => Deno.core.ops.op_gdansk_write_text_file(path, content),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw new Error(`[${plugin.name}] build hook failed: ${message}`);
    }
  }
}
