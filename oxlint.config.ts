import { defineConfig } from "oxlint";

export default defineConfig({
  ignorePatterns: ["src/gdansk/cli/templates/**"],
  plugins: ["react", "react-perf", "import"],
});
