import type { GdanskManifest } from "./types";
export declare const GDANSK_MANIFEST_FILENAME = "gdansk-manifest.json";
export declare function buildProject(root: string, outDirectory: string): Promise<GdanskManifest>;
