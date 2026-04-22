import { gdanskPages } from "@gdansk/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [gdanskPages({ refresh: true }), react()],
});
