import { render } from "@gdansk/widget";
import { createElement } from "react";

function App() {
  return createElement(
    "main",
    null,
    createElement("h2", null, "Simple Production Example"),
    createElement("p", null, "This markup is rendered on the server first, then hydrated in the browser."),
  );
}

export default function widget() {
  return render({ metadata: { title: "Production Example" }, widget: createElement(App) });
}
