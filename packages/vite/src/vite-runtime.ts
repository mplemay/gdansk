type ViteModule = typeof import("vite");

let viteModulePromise: Promise<ViteModule> | undefined;

function viteImportSpecifier(): "vite" | "npm:vite" {
  return typeof (globalThis as { Deno?: unknown }).Deno === "undefined" ? "vite" : "npm:vite";
}

export async function loadViteModule(): Promise<ViteModule> {
  viteModulePromise ??= import(viteImportSpecifier()) as Promise<ViteModule>;
  return viteModulePromise;
}
