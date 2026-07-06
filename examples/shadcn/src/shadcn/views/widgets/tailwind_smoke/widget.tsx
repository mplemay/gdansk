import tailwindcss from "@tailwindcss/vite";
import { render } from "@gdansk/widget";

import "../../global.css";

function App() {
  return <main className="mx-auto w-full max-w-xl">Tailwind Smoke</main>;
}

export default function widget() {
  return render({
    metadata: { title: "Tailwind Smoke" },
    plugins: [tailwindcss()],
    widget: <App />,
  });
}
