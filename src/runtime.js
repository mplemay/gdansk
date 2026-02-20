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
