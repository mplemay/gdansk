import { createElement } from "react";

export default function App() {
  return createElement(
    "main",
    null,
    createElement("h2", null, "Simple SSR Example"),
    createElement("p", null, "This markup is rendered on the server first, then hydrated in the browser."),
  );
}
