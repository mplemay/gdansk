import { defineConfig } from "oxlint";

// `plugins` replaces oxlint's default set; only the listed plugins are active (no typescript/oxc/unicorn unless added).
export default defineConfig({
  $schema: "./node_modules/oxlint/configuration_schema.json",
  options: {
    typeAware: true,
    typeCheck: true,
  },
  plugins: ["react", "react-perf", "import"],
});
