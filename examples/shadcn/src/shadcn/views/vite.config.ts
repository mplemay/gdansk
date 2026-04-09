import { fileURLToPath } from "node:url";

import gdansk from "@gdansk/vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const root = fileURLToPath(new URL("./", import.meta.url));

export default defineConfig({
  plugins: [gdansk(), react(), tailwindcss()],
  resolve: {
    alias: {
      "@": root,
    },
  },
});
