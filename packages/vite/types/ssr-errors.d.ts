import type { GdanskSSRErrorDiagnostic, GdanskSSRErrorPayload } from "./types";
export declare function classifyRenderError(error: unknown, widget?: string): GdanskSSRErrorDiagnostic;
export declare function createSSRErrorPayload(payload: GdanskSSRErrorPayload): {
  error: GdanskSSRErrorPayload;
};
export declare function formatSSRError(diagnostic: GdanskSSRErrorDiagnostic, root?: string): string;
