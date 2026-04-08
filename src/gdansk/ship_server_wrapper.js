import { createElement } from "react";
import { renderToString } from "react-dom/server";
import App from "__GDANSK_WIDGET_IMPORT__";

export default function render() {
  return renderToString(createElement(App));
}
