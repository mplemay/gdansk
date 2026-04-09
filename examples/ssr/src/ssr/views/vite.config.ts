import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import gdansk from "@gdansk/vite";

export default defineConfig({
  plugins: [gdansk(), react()],
});
