import { type Plugin } from "vite";
import type { GdanskDevelopmentManifest, GdanskManifest, WidgetDefinition, WidgetSource } from "./types";
export declare function toPosixPath(path: string): string;
export declare function discoverWidgets(root: string): Promise<WidgetSource[]>;
export declare function loadWidgetDefinition(root: string, widget: WidgetSource): Promise<WidgetDefinition>;
export declare function resolveWidgetPlugins(definition: WidgetDefinition): Promise<Plugin[]>;
export declare function writeJson(path: string, value: GdanskManifest | GdanskDevelopmentManifest): Promise<void>;
export declare function widgetRelativeEntry(root: string, entry: string): string;
