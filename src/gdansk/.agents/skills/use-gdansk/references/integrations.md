# Integrations

## Metadata

HTML metadata lives in each TypeScript descriptor:

```tsx
import { render } from "@gdansk/widget";
import { sharedMetadata } from "../../metadata.ts";

export default function widget() {
  return render({ metadata: { ...sharedMetadata, title: "Orders" }, widget: <Orders /> });
}
```

Keep MCP metadata such as CSP, visibility, resource URI, icons, and tool annotations on Python's
`@ship.widget(...)` decorator.

## Tailwind and other Vite plugins

```tsx
import tailwindcss from "@tailwindcss/vite";
import { render } from "@gdansk/widget";

export default function widget() {
  return render({
    plugins: [tailwindcss()],
    widget: <App />,
  });
}
```

Declare the plugin in `[gdansk.dependencies]`. Gdansk strips `plugins` and their imports from the browser bundle;
declare plugins inline in `render({ plugins: [...] })`.

## Per-widget Vite settings

The descriptor's optional `vite` object supports resolution, CSS, `define`, and optimization settings. Gdansk owns
`root`, `configFile`, `server`, `build`, `builder`, and `environments`.

## FastAPI

Mount `mcp.streamable_http_app()` into FastAPI and run `ship.mcp(app=mcp, watch=...)` in the MCP server lifespan.
Production pages are self-contained; no widget static-files mount is needed.
