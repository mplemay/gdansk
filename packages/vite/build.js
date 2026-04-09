#!/usr/bin/env node
import esbuild from "esbuild";
import { nodeExternalsPlugin } from "esbuild-node-externals";

const watch = process.argv.slice(2).includes("--watch");

const context = await esbuild.context({
  bundle: true,
  entryPoints: ["src/index.ts"],
  format: "esm",
  minify: false,
  outfile: "dist/index.js",
  platform: "node",
  plugins: [nodeExternalsPlugin()],
  sourcemap: true,
  target: "es2023",
});

if (watch) {
  console.log("Watching src/index.ts (esm)...");
  await context.watch();
} else {
  await context.rebuild();
  await context.dispose();
  console.log("Built src/index.ts (esm)...");
}
