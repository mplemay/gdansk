import type { Metadata } from "./types";
export declare function escapeInlineScript(value: string): string;
export declare function escapeInlineStyle(value: string): string;
export declare function renderDocument(options: {
    inlineScript?: string;
    metadata?: Metadata | undefined;
    scripts?: string[];
    styles?: string[];
}): string;
