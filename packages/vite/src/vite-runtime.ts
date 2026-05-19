type ViteModule = typeof import("vite");

let viteModulePromise: Promise<ViteModule> | undefined;

export async function loadViteModule(): Promise<ViteModule> {
  viteModulePromise ??= import("vite") as Promise<ViteModule>;
  return viteModulePromise;
}
