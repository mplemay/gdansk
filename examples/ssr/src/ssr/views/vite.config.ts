import gdansk from "@gdansk/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [gdansk({ ssr: true, refresh: true }), react()],
});
