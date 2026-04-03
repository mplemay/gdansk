import { core } from "ext:core/mod.js";
import * as abortSignal from "ext:deno_web/03_abort_signal.js";
import * as base64 from "ext:deno_web/05_base64.js";
import { DOMException } from "ext:deno_web/01_dom_exception.js";
import * as encoding from "ext:deno_web/08_text_encoding.js";
import * as file from "ext:deno_web/09_file.js";
import * as messagePort from "ext:deno_web/13_message_port.js";
import * as performance from "ext:deno_web/15_performance.js";
import * as streams from "ext:deno_web/06_streams.js";
import * as url from "ext:deno_web/00_url.js";
import * as webidl from "ext:deno_webidl/00_webidl.js";

let nextTimerId = 1;
const activeTimers = new Map();

function timerCallback(callback, args) {
  if (typeof callback === "function") {
    return () => callback(...args);
  }
  return () => (0, eval)(String(callback));
}

function defer(callback) {
  Promise.resolve().then(() => callback());
}

function scheduleTimer(callback, args, repeat) {
  const id = nextTimerId;
  nextTimerId += 1;
  const handler = timerCallback(callback, args);
  activeTimers.set(id, repeat);

  const tick = () => {
    if (!activeTimers.has(id)) {
      return;
    }
    handler();
    if (activeTimers.get(id)) {
      defer(tick);
      return;
    }
    activeTimers.delete(id);
  };

  defer(tick);
  return id;
}

function setTimeout(callback, _delay = 0, ...args) {
  return scheduleTimer(callback, args, false);
}

function setInterval(callback, _delay = 0, ...args) {
  return scheduleTimer(callback, args, true);
}

function clearTimeout(timerId = 0) {
  activeTimers.delete(timerId);
}

function clearInterval(timerId = 0) {
  activeTimers.delete(timerId);
}

Object.defineProperties(globalThis, {
  AbortController: core.propNonEnumerable(abortSignal.AbortController),
  AbortSignal: core.propNonEnumerable(abortSignal.AbortSignal),
  Blob: core.propNonEnumerable(file.Blob),
  DOMException: core.propNonEnumerable(DOMException),
  File: core.propNonEnumerable(file.File),
  MessageChannel: core.propNonEnumerable(messagePort.MessageChannel),
  MessagePort: core.propNonEnumerable(messagePort.MessagePort),
  ReadableStream: core.propNonEnumerable(streams.ReadableStream),
  TextDecoder: core.propNonEnumerable(encoding.TextDecoder),
  TextEncoder: core.propNonEnumerable(encoding.TextEncoder),
  TransformStream: core.propNonEnumerable(streams.TransformStream),
  URL: core.propNonEnumerable(url.URL),
  URLSearchParams: core.propNonEnumerable(url.URLSearchParams),
  WritableStream: core.propNonEnumerable(streams.WritableStream),
  atob: core.propWritable(base64.atob),
  btoa: core.propWritable(base64.btoa),
  clearInterval: core.propWritable(clearInterval),
  clearTimeout: core.propWritable(clearTimeout),
  performance: core.propWritable(performance.performance),
  setInterval: core.propWritable(setInterval),
  setTimeout: core.propWritable(setTimeout),
  structuredClone: core.propWritable(messagePort.structuredClone),
  [webidl.brand]: core.propNonEnumerable(webidl.brand),
});
