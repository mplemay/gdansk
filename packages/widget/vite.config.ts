import { defineConfig } from "vite";

export default defineConfig({
  build: {
    copyPublicDir: false,
    minify: false,
    outDir: "dist",
    rolldownOptions: {
      input: {
        client: "src/client.ts",
        cli: "src/cli.ts",
        index: "src/index.ts",
        runtime: "src/runtime-entry.ts",
      },
      output: {
        entryFileNames: "[name].js",
      },
    },
    ssr: true,
    sourcemap: true,
    target: "es2023",
  },
  ssr: {
    external: true,
    target: "node",
  },
});
