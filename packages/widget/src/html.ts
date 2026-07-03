import { renderMetadata } from "./metadata";
import type { Metadata } from "./types";

export function escapeInlineScript(value: string): string {
  return value.replace(/<\/script/gi, "<\\/script");
}

export function escapeInlineStyle(value: string): string {
  return value.replace(/<\/style/gi, "<\\/style");
}

export function renderDocument(options: {
  inlineScript?: string;
  metadata?: Metadata | undefined;
  scripts?: string[];
  styles?: string[];
}): string {
  const head = [
    '<meta charset="utf-8" />',
    '<meta name="viewport" content="width=device-width, initial-scale=1" />',
    renderMetadata(options.metadata),
    ...(options.styles ?? []).map((style) => `<style>${escapeInlineStyle(style)}</style>`),
  ].filter(Boolean);
  const scripts = [
    ...(options.scripts ?? []).map((script) => `<script type="module" src="${script}"></script>`),
    ...(options.inlineScript ? [`<script type="module">${escapeInlineScript(options.inlineScript)}</script>`] : []),
  ];
  return `<!DOCTYPE html>\n<html>\n<head>\n${head.join("\n")}\n</head>\n<body>\n<div id="root"></div>\n${scripts.join("\n")}\n</body>\n</html>\n`;
}
