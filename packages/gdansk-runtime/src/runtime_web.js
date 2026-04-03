import { core, primordials } from "ext:core/mod.js";
const { indirectEval, ObjectSetPrototypeOf, ReflectApply } = primordials;

import * as url from "ext:deno_web/00_url.js";
import { DOMException, QuotaExceededError } from "ext:deno_web/01_dom_exception.js";
import * as urlPattern from "ext:deno_web/01_urlpattern.js";
import * as broadcastChannel from "ext:deno_web/01_broadcast_channel.js";
import * as event from "ext:deno_web/02_event.js";
import * as abortSignal from "ext:deno_web/03_abort_signal.js";
import * as globalInterfaces from "ext:deno_web/04_global_interfaces.js";
import * as base64 from "ext:deno_web/05_base64.js";
import * as streams from "ext:deno_web/06_streams.js";
import * as encoding from "ext:deno_web/08_text_encoding.js";
import * as file from "ext:deno_web/09_file.js";
import * as fileReader from "ext:deno_web/10_filereader.js";
import * as location from "ext:deno_web/12_location.js";
import * as messagePort from "ext:deno_web/13_message_port.js";
import * as compression from "ext:deno_web/14_compression.js";
import * as performance from "ext:deno_web/15_performance.js";
import * as imageData from "ext:deno_web/16_image_data.js";
import * as webidl from "ext:deno_webidl/00_webidl.js";

let nextTimerId = 1;
const activeTimers = new Map();

function timerCallback(callback, args) {
  if (typeof callback !== "function") {
    const unboundCallback = webidl.converters.DOMString(callback);
    return () => indirectEval(unboundCallback);
  }
  return () => ReflectApply(callback, globalThis, args);
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

performance.setTimeOrigin();
event.setEventTargetData(globalThis);
event.saveGlobalThisReference(globalThis);
ObjectSetPrototypeOf(globalThis, globalInterfaces.Window.prototype);
event.defineEventHandler(globalThis, "error");
event.defineEventHandler(globalThis, "unhandledrejection");

Object.defineProperties(globalThis, {
  AbortController: core.propNonEnumerable(abortSignal.AbortController),
  AbortSignal: core.propNonEnumerable(abortSignal.AbortSignal),
  Blob: core.propNonEnumerable(file.Blob),
  BroadcastChannel: core.propNonEnumerable(broadcastChannel.BroadcastChannel),
  ByteLengthQueuingStrategy: core.propNonEnumerable(
    streams.ByteLengthQueuingStrategy,
  ),
  CloseEvent: core.propNonEnumerable(event.CloseEvent),
  CompressionStream: core.propNonEnumerable(compression.CompressionStream),
  CountQueuingStrategy: core.propNonEnumerable(
    streams.CountQueuingStrategy,
  ),
  CustomEvent: core.propNonEnumerable(event.CustomEvent),
  DedicatedWorkerGlobalScope:
    globalInterfaces.dedicatedWorkerGlobalScopeConstructorDescriptor,
  DecompressionStream: core.propNonEnumerable(
    compression.DecompressionStream,
  ),
  DOMException: core.propNonEnumerable(DOMException),
  ErrorEvent: core.propNonEnumerable(event.ErrorEvent),
  Event: core.propNonEnumerable(event.Event),
  EventTarget: core.propNonEnumerable(event.EventTarget),
  File: core.propNonEnumerable(file.File),
  FileReader: core.propNonEnumerable(fileReader.FileReader),
  ImageData: core.propNonEnumerable(imageData.ImageData),
  Location: location.locationConstructorDescriptor,
  MessageChannel: core.propNonEnumerable(messagePort.MessageChannel),
  MessageEvent: core.propNonEnumerable(event.MessageEvent),
  MessagePort: core.propNonEnumerable(messagePort.MessagePort),
  Performance: core.propNonEnumerable(performance.Performance),
  PerformanceEntry: core.propNonEnumerable(performance.PerformanceEntry),
  PerformanceMark: core.propNonEnumerable(performance.PerformanceMark),
  PerformanceMeasure: core.propNonEnumerable(performance.PerformanceMeasure),
  PerformanceObserver: core.propNonEnumerable(
    performance.PerformanceObserver,
  ),
  PerformanceObserverEntryList: core.propNonEnumerable(
    performance.PerformanceObserverEntryList,
  ),
  ProgressEvent: core.propNonEnumerable(event.ProgressEvent),
  PromiseRejectionEvent: core.propNonEnumerable(
    event.PromiseRejectionEvent,
  ),
  QuotaExceededError: core.propNonEnumerable(QuotaExceededError),
  ReadableByteStreamController: core.propNonEnumerable(
    streams.ReadableByteStreamController,
  ),
  ReadableStream: core.propNonEnumerable(streams.ReadableStream),
  ReadableStreamBYOBReader: core.propNonEnumerable(
    streams.ReadableStreamBYOBReader,
  ),
  ReadableStreamBYOBRequest: core.propNonEnumerable(
    streams.ReadableStreamBYOBRequest,
  ),
  ReadableStreamDefaultController: core.propNonEnumerable(
    streams.ReadableStreamDefaultController,
  ),
  ReadableStreamDefaultReader: core.propNonEnumerable(
    streams.ReadableStreamDefaultReader,
  ),
  TextDecoder: core.propNonEnumerable(encoding.TextDecoder),
  TextDecoderStream: core.propNonEnumerable(
    encoding.TextDecoderStream,
  ),
  TextEncoder: core.propNonEnumerable(encoding.TextEncoder),
  TextEncoderStream: core.propNonEnumerable(
    encoding.TextEncoderStream,
  ),
  TransformStream: core.propNonEnumerable(streams.TransformStream),
  TransformStreamDefaultController: core.propNonEnumerable(
    streams.TransformStreamDefaultController,
  ),
  URL: core.propNonEnumerable(url.URL),
  URLPattern: core.propNonEnumerable(urlPattern.URLPattern),
  URLSearchParams: core.propNonEnumerable(url.URLSearchParams),
  Window: globalInterfaces.windowConstructorDescriptor,
  WorkerGlobalScope: globalInterfaces.workerGlobalScopeConstructorDescriptor,
  WorkerLocation: location.workerLocationConstructorDescriptor,
  WritableStream: core.propNonEnumerable(streams.WritableStream),
  WritableStreamDefaultController: core.propNonEnumerable(
    streams.WritableStreamDefaultController,
  ),
  WritableStreamDefaultWriter: core.propNonEnumerable(
    streams.WritableStreamDefaultWriter,
  ),
  atob: core.propWritable(base64.atob),
  btoa: core.propWritable(base64.btoa),
  clearInterval: core.propWritable(clearInterval),
  clearTimeout: core.propWritable(clearTimeout),
  location: core.propWritable(undefined),
  performance: core.propWritable(performance.performance),
  reportError: core.propWritable(event.reportError),
  setInterval: core.propWritable(setInterval),
  setTimeout: core.propWritable(setTimeout),
  structuredClone: core.propWritable(messagePort.structuredClone),
  [webidl.brand]: core.propNonEnumerable(webidl.brand),
});
