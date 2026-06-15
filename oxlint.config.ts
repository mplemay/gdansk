import { defineConfig } from "oxlint";

export default defineConfig({
  ignorePatterns: ["src/gdansk/_cli_templates/**"],
  plugins: ["react", "react-perf", "import"],
});
