import type { GdanskSSRErrorDiagnostic, GdanskSSRErrorPayload } from "./types";

const BROWSER_APIS: Record<string, string> = {
  BroadcastChannel: "The BroadcastChannel constructor",
  Image: "The Image constructor",
  IntersectionObserver: "The IntersectionObserver API",
  MutationObserver: "The MutationObserver API",
  ResizeObserver: "The ResizeObserver API",
  Worker: "The Worker constructor",
  XMLHttpRequest: "The XMLHttpRequest API",
  document: "The DOM document object",
  fetch: "The fetch API",
  history: "The browser history API",
  localStorage: "Browser local storage",
  location: "The location object",
  matchMedia: "The matchMedia function",
  navigator: "The navigator object",
  requestAnimationFrame: "The requestAnimationFrame function",
  requestIdleCallback: "The requestIdleCallback function",
  screen: "The screen object",
  sessionStorage: "Browser session storage",
  window: "The global window object",
};

const LIFECYCLE_HOOKS = "useEffect";

const colors = {
  bgRed: "\x1b[41m",
  bold: "\x1b[1m",
  cyan: "\x1b[36m",
  dim: "\x1b[2m",
  reset: "\x1b[0m",
  white: "\x1b[37m",
  yellow: "\x1b[33m",
};

export function classifyRenderError(error: unknown, widget?: string): GdanskSSRErrorDiagnostic {
  const normalized = toError(error);
  const browserApi = detectBrowserApi(normalized);

  if (browserApi) {
    return {
      hint: getBrowserApiHint(browserApi),
      message: normalized.message,
      source: extractSourceLocation(normalized.stack),
      stack: normalized.stack,
      type: "browser_api",
      widget,
    };
  }

  if (isComponentResolutionError(normalized)) {
    return {
      hint: getComponentResolutionHint(widget),
      message: normalized.message,
      source: extractSourceLocation(normalized.stack),
      stack: normalized.stack,
      type: "component_resolution",
      widget,
    };
  }

  return {
    hint: getRenderErrorHint(),
    message: normalized.message,
    source: extractSourceLocation(normalized.stack),
    stack: normalized.stack,
    type: "render_error",
    widget,
  };
}

export function createSSRErrorPayload(payload: GdanskSSRErrorPayload): { error: GdanskSSRErrorPayload } {
  return { error: payload };
}

export function formatSSRError(diagnostic: GdanskSSRErrorDiagnostic, root?: string): string {
  const widget = diagnostic.widget ? `  ${colors.cyan}${diagnostic.widget}${colors.reset}` : "";
  const lines = [
    "",
    `  ${colors.bgRed}${colors.white}${colors.bold} GDANSK SSR ERROR ${colors.reset}${widget}`,
    "",
    `  ${diagnostic.message}`,
  ];

  if (diagnostic.source) {
    lines.push(`  ${colors.dim}Source: ${makeRelative(diagnostic.source, root)}${colors.reset}`);
  }

  if (diagnostic.hint) {
    lines.push("", `  ${colors.yellow}Hint${colors.reset}  ${diagnostic.hint}`);
  }

  if (diagnostic.stack) {
    lines.push("", `  ${colors.dim}${diagnostic.stack.split("\n").join("\n  ")}${colors.reset}`);
  }

  lines.push("");

  return lines.join("\n");
}

function detectBrowserApi(error: Error): string | null {
  const message = error.message.toLowerCase();

  for (const api of Object.keys(BROWSER_APIS)) {
    const normalizedApi = api.toLowerCase();
    const patterns = [
      `${normalizedApi} is not defined`,
      `'${normalizedApi}' is not defined`,
      `"${normalizedApi}" is not defined`,
      `cannot read properties of undefined (reading '${normalizedApi}')`,
      `cannot read property '${normalizedApi}'`,
    ];

    if (patterns.some((pattern) => message.includes(pattern))) {
      return api;
    }
  }

  return null;
}

function extractSourceLocation(stack?: string): string | undefined {
  if (!stack) {
    return undefined;
  }

  for (const line of stack.split("\n")) {
    if (!line.includes("at ")) {
      continue;
    }

    if (line.includes("node_modules") || line.includes("node:")) {
      continue;
    }

    let match = line.match(/\(([^)]+):(\d+):(\d+)\)/);

    if (!match) {
      match = line.match(/at\s+(?:file:\/\/)?(.+):(\d+):(\d+)\s*$/);
    }

    if (!match) {
      continue;
    }

    const [, file, lineNumber, columnNumber] = match;
    return `${file.replace(/^file:\/\//, "")}:${lineNumber}:${columnNumber}`;
  }

  return undefined;
}

function getBrowserApiHint(api: string): string {
  const description = BROWSER_APIS[api] ?? `The "${api}" object`;

  if (api === "document" || api === "window") {
    return `${description} does not exist during SSR. Move browser-only code into ${LIFECYCLE_HOOKS} or guard it with "typeof ${api} !== 'undefined'"`;
  }

  if (api === "localStorage" || api === "sessionStorage") {
    return `${description} does not exist during SSR. Access it inside ${LIFECYCLE_HOOKS} or behind a runtime guard.`;
  }

  if (api === "IntersectionObserver" || api === "ResizeObserver" || api === "MutationObserver") {
    return `${description} does not exist during SSR. Create observers inside ${LIFECYCLE_HOOKS}, not at module scope.`;
  }

  return `${description} does not exist during SSR. Move this code behind a browser-only guard or into ${LIFECYCLE_HOOKS}.`;
}

function getComponentResolutionHint(widget?: string): string {
  if (widget) {
    return `Could not resolve code needed to render widget "${widget}". Check the widget import graph, file casing, and package dependencies under the frontend root.`;
  }

  return "Could not resolve code needed during SSR. Check the widget import graph, file casing, and package dependencies under the frontend root.";
}

function getRenderErrorHint(): string {
  return "An error occurred while rendering the widget. Check for browser-only code during initialization and verify SSR-safe module side effects.";
}

function isComponentResolutionError(error: Error): boolean {
  const message = error.message.toLowerCase();
  return (
    message.includes("cannot find module") ||
    message.includes("could not resolve") ||
    message.includes("failed to resolve") ||
    message.includes("module not found")
  );
}

function makeRelative(location: string, root?: string): string {
  const base = root ?? process.cwd();
  return location.startsWith(`${base}/`) ? location.slice(base.length + 1) : location;
}

function toError(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error));
}
