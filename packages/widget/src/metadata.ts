import type { Metadata, Primitive } from "./types";

function escapeAttribute(value: unknown): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function tag(name: string, content: unknown, attribute = "name"): string {
  return `<meta ${attribute}="${escapeAttribute(name)}" content="${escapeAttribute(content)}" />`;
}

function values<T>(value: T | T[] | undefined): T[] {
  if (typeof value === "undefined") return [];
  return Array.isArray(value) ? value : [value];
}

function resolveUrl(value: string, base?: string): string {
  if (!base) return value;
  try {
    return new URL(value, base.endsWith("/") ? base : `${base}/`).href;
  } catch {
    return value;
  }
}

function renderRecord(prefix: string, record: Record<string, unknown>): string[] {
  const output: string[] = [];
  for (const [key, value] of Object.entries(record)) {
    if (value === null || typeof value === "undefined") continue;
    const name = `${prefix}:${key.replace(/[A-Z]/g, (character) => `-${character.toLowerCase()}`)}`;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (typeof item === "object" && item !== null) output.push(...renderRecord(name, item as Record<string, unknown>));
        else output.push(tag(name, item, "property"));
      }
    } else if (typeof value === "object") {
      output.push(...renderRecord(name, value as Record<string, unknown>));
    } else {
      output.push(tag(name, value, "property"));
    }
  }
  return output;
}

export function renderMetadata(metadata?: Metadata): string {
  if (!metadata) return "";
  const output: string[] = [];
  const title = metadata.title;
  if (typeof title === "string") output.push(`<title>${escapeAttribute(title)}</title>`);
  else if (title) {
    const resolved = title.absolute ?? title.default;
    if (resolved) output.push(`<title>${escapeAttribute(resolved)}</title>`);
  }

  const named: Array<[string, unknown]> = [
    ["description", metadata.description],
    ["application-name", metadata.applicationName],
    ["generator", metadata.generator],
    ["referrer", metadata.referrer],
    ["color-scheme", metadata.colorScheme],
    ["creator", metadata.creator],
    ["publisher", metadata.publisher],
    ["abstract", metadata.abstract],
    ["category", metadata.category],
    ["classification", metadata.classification],
  ];
  for (const [name, value] of named) if (typeof value !== "undefined") output.push(tag(name, value));
  if (metadata.keywords) output.push(tag("keywords", values(metadata.keywords).join(", ")));
  if (metadata.viewport) {
    const viewport =
      typeof metadata.viewport === "string"
        ? metadata.viewport
        : Object.entries(metadata.viewport)
            .map(([key, value]) => `${key.replace(/[A-Z]/g, (character) => `-${character.toLowerCase()}`)}=${value}`)
            .join(", ");
    output.push(tag("viewport", viewport));
  }
  for (const theme of values(metadata.themeColor)) {
    if (typeof theme === "string") output.push(tag("theme-color", theme));
    else output.push(`<meta name="theme-color" content="${escapeAttribute(theme.color)}"${theme.media ? ` media="${escapeAttribute(theme.media)}"` : ""} />`);
  }
  for (const author of values(metadata.authors)) {
    if (author.name) output.push(tag("author", author.name));
    if (author.url) output.push(`<link rel="author" href="${escapeAttribute(resolveUrl(author.url, metadata.metadataBase))}" />`);
  }
  if (metadata.manifest) output.push(`<link rel="manifest" href="${escapeAttribute(resolveUrl(metadata.manifest, metadata.metadataBase))}" />`);
  if (metadata.openGraph) output.push(...renderRecord("og", metadata.openGraph));
  if (metadata.twitter) output.push(...renderRecord("twitter", metadata.twitter).map((value) => value.replace('property="', 'name="')));
  for (const [name, value] of Object.entries(metadata.other ?? {})) {
    for (const item of values(value as Primitive | Primitive[])) output.push(tag(name, item));
  }
  return output.join("\n");
}
