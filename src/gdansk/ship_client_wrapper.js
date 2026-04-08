import { StrictMode, createElement } from "react";
import { createRoot, hydrateRoot } from "react-dom/client";
import App from "__GDANSK_WIDGET_IMPORT__";

const root = document.getElementById("root");
if (!root) throw new Error("Expected #root element");
const element = createElement(StrictMode, null, createElement(App));
root.hasChildNodes() ? hydrateRoot(root, element) : createRoot(root).render(element);
