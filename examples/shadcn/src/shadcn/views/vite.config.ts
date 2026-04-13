import gdansk from "@gdansk/vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [gdansk({ refresh: true }), react(), tailwindcss()],
});
