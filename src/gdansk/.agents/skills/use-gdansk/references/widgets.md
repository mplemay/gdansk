# Widgets

A widget module default-exports a function returning `render({...})`:

```tsx
import { useApp } from "@modelcontextprotocol/ext-apps/react";
import { render } from "@gdansk/widget";

function Todo() {
  const { app, error } = useApp({
    appInfo: { name: "Todo", version: "1.0.0" },
    capabilities: {},
  });
  if (error) return <p>{error.message}</p>;
  if (!app) return <p>Connecting...</p>;
  return <button onClick={() => app.callServerTool({ name: "add_todo", arguments: {} })}>Add</button>;
}

export default function widget() {
  return render({ metadata: { title: "Todo" }, widget: <Todo /> });
}
```

The browser mounts only `definition.widget` under React Strict Mode. The Python tool name must match the name passed
to `callServerTool`. Import CSS and assets from the component tree; production inlines them into the page.

Use `structured_output=True` on the Python decorator when the UI consumes structured tool results.
