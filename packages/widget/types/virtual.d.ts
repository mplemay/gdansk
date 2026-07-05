import { type Plugin } from "vite";
import type { WidgetSource } from "./types";
export declare const GDANSK_CLIENT_PATH = "/@gdansk/client.tsx";
export declare function createClientPlugin(widget: WidgetSource): Plugin;
export declare function createBrowserDescriptorPlugin(): Plugin;
export declare function createDescriptorCssPlugin(): Plugin;
