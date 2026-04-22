import { createInertiaApp } from "@inertiajs/react";
import { createRoot } from "react-dom/client";

import "./app.css";

createInertiaApp({
  progress: false,
  resolve: async (name) => {
    const pages = import.meta.glob("./Pages/**/*.tsx");
    const loader = pages[`./Pages/${name}.tsx`];

    if (!loader) {
      throw new Error(`Unknown page component: ${name}`);
    }

    const page = await loader();
    return "default" in page ? page.default : page;
  },
  setup({ App, el, props }) {
    createRoot(el).render(<App {...props} />);
  },
});
