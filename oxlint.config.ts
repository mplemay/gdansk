import { defineConfig } from "oxlint";

export default defineConfig({
  ignorePatterns: ["src/gdansk/_cli_templates/**"],
  options: {
    typeAware: true,
    typeCheck: true,
  },
  plugins: ["react", "react-perf", "import"],
});
