import { defineConfig } from "vite";

export default defineConfig({
  build: {
    copyPublicDir: false,
    minify: false,
    outDir: "dist",
    rolldownOptions: {
      output: {
        entryFileNames: "index.js",
      },
    },
    sourcemap: true,
    ssr: "src/index.ts",
    target: "es2023",
  },
  ssr: {
    external: true,
    target: "node",
  },
});
