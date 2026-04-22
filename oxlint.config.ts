import { defineConfig } from "oxlint";

export default defineConfig({
  ignorePatterns: ["examples/inertia/src/gdansk_inertia_example/views/**/*"],
  options: {
    typeAware: true,
    typeCheck: true,
  },
  plugins: ["react", "react-perf", "import"],
});
