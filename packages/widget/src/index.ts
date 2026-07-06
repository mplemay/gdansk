export { assertWidgetDefinition, render } from "./definition";
export type {
  GdanskDevelopmentManifest,
  GdanskManifest,
  ManifestWidget,
  Metadata,
  RenderOptions,
  WidgetDefinition,
  WidgetViteConfig,
} from "./types";

export async function buildProject(root: string, outDirectory: string): Promise<unknown> {
  return (await import("./build")).buildProject(root, outDirectory);
}

export async function startDevelopment(options: {
  host: string;
  manifest: string;
  port: number;
  root: string;
}): Promise<never> {
  return (await import("./development")).startDevelopment(options);
}
